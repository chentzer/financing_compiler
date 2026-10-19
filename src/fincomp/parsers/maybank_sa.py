"""Maybank savings account statements from Maybank2u ("M2U SA <acct> <Mon>
<YYYY>.pdf"; encrypted with an empty password).

Each transaction is one line plus indented detail lines, which can carry
over to the next page:

    02/09/26 FPX PAYMENT FR A/ 868.79- 531.21
       T100000000001      *          FPX reference
       AEON CREDIT SERVICE           who was paid
       2609020000000001              reference

"+" is money in, "-" money out, the last number the balance. Every row is
checked against the running balance and the TOTAL CREDIT / TOTAL DEBIT /
ENDING BALANCE footer.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..models import Transaction
from .base import ParseError, TextPdfParser

SOURCE = "Maybank"
MONEY = r"[\d,]+\.\d{2}"
LINE_RE = re.compile(rf"^(?P<date>\d{{2}}/\d{{2}}/\d{{2}}) (?P<type>.+?) (?P<amount>{MONEY})(?P<sign>[+-]) (?P<balance>{MONEY})$")
BEGIN_RE = re.compile(rf"^BEGINNING BALANCE ({MONEY})$")
ENDING_RE = re.compile(rf"ENDING BALANCE : ({MONEY})")
CREDIT_RE = re.compile(rf"TOTAL CREDIT : ({MONEY})")
DEBIT_RE = re.compile(rf"TOTAL DEBIT : ({MONEY})")
ACCOUNT_RE = re.compile(r"^: (\d{6}-\d{6})$")
BRANCH_RE = re.compile(r"^\d{6} [A-Z][A-Z .]+$")  # "000001 SUBANG JAYA", just above your name

# Filler in the detail lines: bank references, not what the money was for.
FILLER_RE = re.compile(
    r"^(transfer|fund transfer|mbb ct-?|dbpay|\*|[A-Z]?\d[\d\s-]*|\d{4}-\d{2}ct|T\d{6,}\s*\*?)$",
    re.IGNORECASE,
)
TRANSFER_TYPES = ("IBK FUND TFR", "FUND TRANSFER", "DUITNOW", "INSTANT TRANSFER", "IBG", "INTERBANK")
GIRO_TYPES = ("SVG GIRO CR", "GIRO CR")


def _money(text: str) -> float:
    return float(text.replace(",", ""))


def _clean(line: str) -> str:
    return re.sub(r"\s+\*$", "", line).strip()


def _purpose(details: list[str]) -> str:
    kept = []
    for d in details:
        if not FILLER_RE.match(d) and d not in kept:  # "sep26 netpay" is printed twice
            kept.append(d)
    return " - ".join(kept)


def parse_text(text: str, file: str = "", own_payees: list[str] | None = None) -> list[Transaction]:
    own_payees = [p.upper() for p in (own_payees or [])]
    raw_lines = text.splitlines()
    stripped = [l.strip() for l in raw_lines]
    holder = next((stripped[i + 1] for i, l in enumerate(stripped[:-1]) if BRANCH_RE.match(l)), "").lower()
    account_no = next((m.group(1) for l in stripped if (m := ACCOUNT_RE.match(l))), "")
    account = f"Savings ...{account_no[-4:]}" if account_no else "Savings"

    rows: list[dict] = []
    balance: float | None = None
    for raw, line in zip(raw_lines, stripped):
        if m := BEGIN_RE.match(line):
            balance = _money(m.group(1))
            continue
        if m := LINE_RE.match(line):
            amount = _money(m.group("amount")) * (1 if m.group("sign") == "+" else -1)
            new_balance = _money(m.group("balance"))
            if balance is not None and round(balance + amount, 2) != round(new_balance, 2):
                raise ParseError(
                    f"{file}: balance doesn't add up at '{line}' (expected {balance + amount:,.2f}). "
                    "The PDF layout may have changed."
                )
            balance = new_balance
            rows.append({"line": m, "amount": amount, "details": []})
            continue
        # Indented lines are details of the last transaction, even after a
        # page break; page headers and footers aren't indented.
        if rows and raw.startswith("   ") and line:
            rows[-1]["details"].append(_clean(line))

    transactions = [_transaction(r, holder, account, own_payees, file) for r in rows]
    _check_totals(text, transactions, file)
    return transactions


def _transaction(row: dict, holder: str, account: str, own_payees: list[str], file: str) -> Transaction:
    m, amount, details = row["line"], row["amount"], row["details"]
    kind = m.group("type").strip()
    common = dict(
        date=datetime.strptime(m.group("date"), "%d/%m/%y").date(),
        source=SOURCE, account=account, amount=amount, type=kind, file=file,
    )
    named = [d for d in details if not FILLER_RE.match(d)]
    who = named[0] if named else ""
    description = " - ".join([kind] + details)

    if kind.startswith(TRANSFER_TYPES) or kind.startswith(GIRO_TYPES):
        to_self = bool(holder) and who.lower() == holder
        return Transaction(
            description=description,
            internal=to_self,
            transfer=to_self,
            counterparty=who,
            purpose=_purpose(named[1:]),
            **common,
        )

    # FPX, direct debits, card purchases: paid to a company or shop.
    payee = who or kind
    own = any(p in payee.upper() for p in own_payees)  # e.g. paying your own credit card
    return Transaction(
        description=payee,
        reference=" ".join(d for d in details if FILLER_RE.match(d)),
        internal=own,
        transfer=own,
        note=description,
        **common,
    )


def _check_totals(text: str, transactions: list[Transaction], file: str) -> None:
    credit = round(sum(t.amount for t in transactions if t.amount > 0), 2)
    debit = round(-sum(t.amount for t in transactions if t.amount < 0), 2)
    for label, regex, got in (("TOTAL CREDIT", CREDIT_RE, credit), ("TOTAL DEBIT", DEBIT_RE, debit)):
        if (m := regex.search(text)) and round(_money(m.group(1)), 2) != got:
            raise ParseError(
                f"{file}: rows add up to {label} {got:,.2f} but the statement says {m.group(1)}. "
                "The PDF layout may have changed."
            )


class MaybankSavingsParser(TextPdfParser):
    name = "maybank_sa"
    label = SOURCE
    default_patterns = ["m2u sa *.pdf", "m2u*.pdf"]
    marker = "Malayan Banking Berhad"

    def sniff(self, name: str, data: bytes, password: str = "") -> bool:
        if not super().sniff(name, data, password):
            return False
        try:
            return "ACCOUNT TRANSACTIONS" in self.text(name, data, password)
        except ParseError:
            return True

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        return parse_text(self.text(name, data, password), file=name, own_payees=self.config.own_payees)

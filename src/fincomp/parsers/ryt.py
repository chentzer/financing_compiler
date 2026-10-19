"""Ryt Bank (YTL Digital Bank) statements ("Ryt_Bank_Main_Account_<acct>-
<Mon>-<YYYY>.pdf"; encrypted with an empty password).

Only the Main Account's transactions are listed. A transaction starts with
its date and first description line, then detail lines, then the amount and
balance:

    12 Sep 2026 To BOB LIM AH KOW         who (From/To) or the card merchant
    Transfer                             channel: Transfer / Money movement / Card ••6121
    Dinner share                 your reference
    Ref. ID: 260912AAAA0001
    -55.00 203.65

Foreign card charges put the currency and fee lines between the amount and
the balance. Pockets ("Save Pocket") only appear in the summary table, so
their interest is added from there as one row on the last day.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from ..models import Transaction
from .aeon import purpose_of
from .base import ParseError, TextPdfParser

SOURCE = "Ryt Bank"
MONEY = r"[\d,]+\.\d{2}"
DATE = r"\d{1,2} [A-Z][a-z]{2} \d{4}"
PERIOD_RE = re.compile(rf"^From ({DATE}) to ({DATE})$")
START_RE = re.compile(rf"^({DATE}) (.+)$")
OPENING_RE = re.compile(rf"^Opening balance ({MONEY})$")
AMOUNT_RE = re.compile(rf"^([+-]{MONEY})(?: ({MONEY}))?$")
BALANCE_RE = re.compile(rf"^({MONEY})$")
SUMMARY_RE = re.compile(rf"^({MONEY}) ([+-]{MONEY}) ([+-]?{MONEY}) ([+-]?{MONEY}) ({MONEY})$")
ACCOUNT_RE = re.compile(r"Nombor Akaun Simpanan ([\d ]+)$")
TXN_DATE_RE = re.compile(rf"Transaction date: (\d{{2}} [A-Z][a-z]{{2}} \d{{4}})")
CARD_RE = re.compile(r"^Card\b")


def _money(text: str) -> float:
    return float(text.replace(",", ""))


def _date(text: str) -> date:
    return datetime.strptime(text, "%d %b %Y").date()


def _summary(lines: list[str]) -> list[tuple[str, list[float]]]:
    """(account name, [opening, interest, outgoing, incoming, closing]) for
    the main account and each pocket. The name is two lines above."""
    out = []
    for i, line in enumerate(lines):
        if (m := SUMMARY_RE.match(line)) and i >= 2 and not lines[i - 1].startswith("Jumlah"):
            out.append((lines[i - 2], [_money(g) for g in m.groups()]))
    return out


def parse_text(text: str, file: str = "") -> list[Transaction]:
    lines = [l.strip() for l in text.splitlines()]
    holder = next((lines[i + 1] for i, l in enumerate(lines[:-1]) if l.startswith("Account Holder")), "").lower()
    period = next((m for l in lines if (m := PERIOD_RE.match(l))), None)
    if not period:
        raise ParseError(f"{file}: couldn't find the statement period")
    period_end = _date(period.group(2))
    acct_no = next((m.group(1).replace(" ", "") for l in lines if (m := ACCOUNT_RE.search(l))), "")
    account = f"Main ...{acct_no[-4:]}" if acct_no else "Main"

    summary = _summary(lines)
    main_summary = next((v for name, v in summary if name.startswith("Main")), None)
    pockets = {name: v for name, v in summary if not name.startswith("Main")}
    pocket_names = {p.lower() for p in pockets}

    transactions: list[Transaction] = []
    balance: float | None = None
    block: dict | None = None

    def close(new_balance: float) -> None:
        nonlocal balance, block
        amount = block["amount"]
        if balance is not None and round(balance + amount, 2) != round(new_balance, 2):
            raise ParseError(
                f"{file}: balance doesn't add up at {block['date']} {block['first']} {amount:+.2f} "
                f"(expected {balance + amount:,.2f}, statement says {new_balance:,.2f})."
            )
        balance = new_balance
        transactions.append(_transaction(block, holder, pocket_names, account, file))
        block = None

    for line in lines:
        if not line:
            continue
        if block and block.get("amount") is not None:
            # Waiting for the balance after a foreign-currency charge.
            if m := BALANCE_RE.match(line):
                close(_money(m.group(1)))
            else:
                block["foreign"].append(line)
            continue
        if m := START_RE.match(line):
            first = m.group(2).strip()
            if om := OPENING_RE.match(first):
                balance = _money(om.group(1))
                continue
            block = {"date": _date(m.group(1)), "first": first, "details": [], "amount": None, "foreign": []}
            continue
        if not block:
            continue
        if m := AMOUNT_RE.match(line):
            block["amount"] = _money(m.group(1))
            if m.group(2):
                close(_money(m.group(2)))
            continue
        block["details"].append(line)

    if main_summary:
        _check(transactions, main_summary, file)

    # Pocket interest is only in the summary table.
    for name, (_, interest, *_rest) in pockets.items():
        if interest:
            transactions.append(Transaction(
                date=period_end, source=SOURCE, account=name, description=f"Interest earned - {name}",
                amount=interest, type="Interest", purpose="Interest earned", file=file,
            ))
    return transactions


def _transaction(block: dict, holder: str, pockets: set[str], account: str, file: str) -> Transaction:
    first, details = block["first"], block["details"]
    refs = [d for d in details if d.startswith("Ref. ID")]
    info = [d for d in details if not d.startswith("Ref. ID")]
    common = dict(source=SOURCE, account=account, amount=block["amount"], file=file)
    note = " | ".join(refs + block["foreign"])

    if first.startswith("Daily interest payout"):
        return Transaction(date=block["date"], description="Daily interest payout", type="Interest",
                           purpose="Interest earned", note=note, **common)

    if m := re.match(r"^(From|To) (.+)$", first):
        who = m.group(2).strip()
        channel = info[0] if info else ""
        pocket_move = who.lower() in pockets or channel.lower() == "money movement"
        to_self = bool(holder) and who.lower() == holder
        return Transaction(
            date=block["date"],
            description=" - ".join([first] + info),
            type=channel,
            internal=pocket_move or to_self,
            transfer=to_self,
            counterparty="" if pocket_move else who,
            purpose=purpose_of(info[1:]),
            note=note,
            **common,
        )

    # Card purchase: the first line is the merchant, and the real date is in
    # the Ref. ID line ("Transaction date: 02 Sep 2026").
    when = block["date"]
    for r in refs:
        if dm := TXN_DATE_RE.search(r):
            when = _date(dm.group(1))
    return Transaction(date=when, description=first, type=info[0] if info else "Card", note=note, **common)


def _check(transactions: list[Transaction], summary: list[float], file: str) -> None:
    _, interest, outgoing, incoming, _ = summary
    got_interest = round(sum(t.amount for t in transactions if t.type == "Interest"), 2)
    got_in = round(sum(t.amount for t in transactions if t.amount > 0 and t.type != "Interest"), 2)
    got_out = round(sum(t.amount for t in transactions if t.amount < 0), 2)
    if (got_interest, got_in, got_out) != (round(interest, 2), round(incoming, 2), round(outgoing, 2)):
        raise ParseError(
            f"{file}: rows add up to interest {got_interest:+.2f} / in {got_in:+.2f} / out {got_out:+.2f}, "
            f"but the summary says {interest:+.2f} / {incoming:+.2f} / {outgoing:+.2f}."
        )


class RytParser(TextPdfParser):
    name = "ryt"
    label = SOURCE
    default_patterns = ["ryt_bank*.pdf", "ryt bank*.pdf"]

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        return parse_text(self.text(name, data, password), file=name)

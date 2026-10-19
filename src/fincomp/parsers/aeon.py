"""AEON Bank deposit statements (Deposits-statement-<membership>-<YYYYMM>.pdf).

One PDF holds a section per account, each starting with "Account summary"
and the account name (the main "Savings Account-i" and the "Savings" pot).
Transaction lines in the text layer look like:

    05 Sep 26 SOMEONE - DuitNowID - lunch -RM 16.40 RM 82.40
    16 Sep 26 FRIEND - DuitNowQR - DuitNow QR RM 107.00 RM 113.01

"-RM" is a withdrawal, "RM" a deposit, the last amount the balance. Every
row is checked against the running balance, so a misread line fails loudly.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..models import Transaction
from .base import ParseError, TextPdfParser

SOURCE = "AEON Bank"
LINE_RE = re.compile(
    r"^(?P<date>\d{2} [A-Za-z]{3} \d{2}) (?P<desc>.+?) (?P<amount>-?RM [\d,]+\.\d{2}) (?P<balance>-?RM [\d,]+\.\d{2})$"
)
OPENING_RE = re.compile(r"^\d{2} [A-Za-z]{3} \d{2} Opening balance (?P<balance>-?RM [\d,]+\.\d{2})$")
ACCOUNT_NO_RE = re.compile(r"^\d{10,}$")
POT_MOVES = ("transfer to pot", "transfer to account")
# References the bank or app fills in by itself: they say nothing about
# what the money was for.
GENERIC_NOTES = {
    "transfer", "fund transfer", "funds transfer", "instant transfer", "duitnow", "duitnow qr",
    "duitnow transfer", "qr payment", "payment", "transaction",
}
REF_RE = re.compile(r"^(qr ref no:?\s*)?[\d\s]+$", re.IGNORECASE)


def purpose_of(notes: list[str]) -> str:
    """The user's own payment reference, or "" when there's only filler."""
    kept = [n for n in notes if n and n.lower() not in GENERIC_NOTES and not REF_RE.match(n)]
    return " - ".join(kept)


def _rm(text: str) -> float:
    value = float(text.replace("RM", "").replace(",", "").replace(" ", "").replace("-", ""))
    return -value if text.strip().startswith("-") else value


def _holder(lines: list[str]) -> str:
    """The account holder's name sits just above "Membership no."."""
    for prev, line in zip(lines, lines[1:]):
        if line.startswith("Membership no"):
            return prev.strip()
    return ""


def parse_text(text: str, file: str = "") -> list[Transaction]:
    lines = [l.strip() for l in text.splitlines()]
    holder = _holder(lines).lower()

    # Account names first, so moves between them can be recognised.
    names = [lines[i + 1] for i, l in enumerate(lines[:-1]) if l == "Account summary"]
    own_accounts = {n.lower() for n in names}

    transactions: list[Transaction] = []
    account = ""
    balance: float | None = None
    for i, line in enumerate(lines):
        if line == "Account summary" and i + 1 < len(lines):
            account = lines[i + 1]
            if i + 2 < len(lines) and ACCOUNT_NO_RE.match(lines[i + 2]):
                account = f"{account} ...{lines[i + 2][-4:]}"
            balance = None
            continue
        if m := OPENING_RE.match(line):
            balance = _rm(m.group("balance"))
            continue
        m = LINE_RE.match(line)
        if not m or not account:
            continue

        amount = _rm(m.group("amount"))
        new_balance = _rm(m.group("balance"))
        if balance is not None and round(balance + amount, 2) != round(new_balance, 2):
            raise ParseError(
                f"{file}: balance doesn't add up at '{line}' "
                f"(expected RM {balance + amount:,.2f}). The PDF layout may have changed."
            )
        balance = new_balance

        description = m.group("desc").strip()
        parts = [p.strip() for p in description.split(" - ")]
        counterparty = parts[0].lower()
        channel = parts[1] if len(parts) > 1 else ""

        # Between the main account and the pot in this same statement.
        pot_move = counterparty in own_accounts and channel.lower() in POT_MOVES
        # DuitNow to/from your own name: money moving to another bank or
        # wallet of yours. Paired with the other side if that's imported.
        to_self = bool(holder) and counterparty == holder
        if counterparty in own_accounts and not pot_move:
            # The bank itself, e.g. "Savings - Profit Earned".
            who, purpose = "", channel
        else:
            who, purpose = parts[0], purpose_of(parts[2:])

        transactions.append(
            Transaction(
                date=datetime.strptime(m.group("date"), "%d %b %y").date(),
                source=SOURCE,
                account=account,
                description=description,
                amount=amount,
                type=channel,
                internal=pot_move or to_self,
                transfer=to_self,
                counterparty=who,
                purpose=purpose,
                file=file,
            )
        )
    return transactions


class AeonParser(TextPdfParser):
    name = "aeon"
    label = SOURCE
    default_patterns = ["*deposits-statement-*.pdf"]  # unique enough: no content sniffing

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        text = self.text(name, data, password)
        if "AEON Bank" not in text:
            raise ParseError(f"{name}: doesn't look like an AEON Bank statement")
        return parse_text(text, file=name)

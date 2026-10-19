"""GX Bank savings statements (<account number>-<YYYY>-<MM>-statement.pdf).

Each transaction spans several lines of the text layer:

    4 Sep                      date (the year is the statement's)
    10:01 PM                   time
    Grab Ride                  who: a shop, or a person for DuitNow
    GX Account                 how: GX Account / QR payment / Duitnow - Account
                               number (wrapped over two lines), then your
                               DuitNow reference if any
    -34.00 121.70              amount, balance

"Interest earned +0.01 118.71" is a one-line row. Every row is checked
against the running balance and the page-end totals.
"""

from __future__ import annotations

import re
from datetime import date

from ..models import Transaction
from .aeon import purpose_of
from .base import ParseError, TextPdfParser

SOURCE = "GX Bank"
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
MONEY = r"[\d,]+\.\d{2}"

PERIOD_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})$")
DATE_RE = re.compile(r"^(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?: (\d{4}))?$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2} [AP]M$")
OPENING_RE = re.compile(rf"^Opening balance ({MONEY})$")
INTEREST_RE = re.compile(rf"^Interest earned ([+-]{MONEY}) ({MONEY})$")
AMOUNT_RE = re.compile(rf"^([+-]{MONEY}) ({MONEY})$")
TOTALS_RE = re.compile(rf"^([+-]{MONEY}) ([+-]{MONEY}) ([+-]{MONEY}) ({MONEY})$")
ACCOUNT_RE = re.compile(r"^Account number ([\d-]+)$")

# How the money moved; whatever follows a DuitNow channel is your reference.
DUITNOW_CHANNELS = ["Duitnow - Account number", "Duitnow - Mobile number", "Duitnow - IC number", "Duitnow"]


def _money(text: str) -> float:
    return float(text.replace(",", ""))


def _holder(lines: list[str]) -> str:
    """The account holder's name is the first line after "Page 1-N"."""
    for i, line in enumerate(lines):
        if line.startswith("Page 1-"):
            return next((l for l in lines[i + 1:] if l), "")
    return ""


def parse_text(text: str, file: str = "") -> list[Transaction]:
    lines = [l.strip() for l in text.splitlines()]
    holder = _holder(lines).lower()
    period = next((PERIOD_RE.match(l) for l in lines if PERIOD_RE.match(l)), None)
    if not period:
        raise ParseError(f"{file}: couldn't find the statement month")
    stmt_year = int(period.group(2))
    stmt_month = ["January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"].index(period.group(1)) + 1
    account_no = next((m.group(1) for l in lines if (m := ACCOUNT_RE.match(l))), "")
    account = f"Savings ...{account_no.replace('-', '')[-4:]}" if account_no else "Savings"

    def when(m: re.Match) -> date:
        month = MONTHS[m.group(2)]
        year = int(m.group(3)) if m.group(3) else stmt_year - (1 if month > stmt_month else 0)
        return date(year, month, int(m.group(1)))

    transactions: list[Transaction] = []
    balance: float | None = None
    current: date | None = None
    desc: list[str] = []
    open_block = False
    totals = None

    def add(amount: float, new_balance: float, t: Transaction) -> None:
        nonlocal balance
        if balance is not None and round(balance + amount, 2) != round(new_balance, 2):
            raise ParseError(
                f"{file}: balance doesn't add up at {t.date} {t.description} {amount:+.2f} "
                f"(expected {balance + amount:,.2f}, statement says {new_balance:,.2f})."
            )
        balance = new_balance
        transactions.append(t)

    for line in lines:
        if not line:
            continue
        if m := DATE_RE.match(line):
            current, desc, open_block = when(m), [], True
            continue
        if TIME_RE.match(line):
            continue
        if m := OPENING_RE.match(line):
            balance, open_block = _money(m.group(1)), False
            continue
        if m := TOTALS_RE.match(line):
            totals = [_money(g) for g in m.groups()]
            continue
        if (m := INTEREST_RE.match(line)) and current:
            amount = _money(m.group(1))
            add(amount, _money(m.group(2)), Transaction(
                date=current, source=SOURCE, account=account, description="Interest earned",
                amount=amount, type="Interest", purpose="Interest earned", file=file,
            ))
            open_block = False
            continue
        if (m := AMOUNT_RE.match(line)) and open_block and desc:
            amount = _money(m.group(1))
            add(amount, _money(m.group(2)), _transaction(current, desc, amount, holder, account, file))
            open_block = False
            continue
        if open_block:
            desc.append(line)

    if totals:
        money_in = round(sum(t.amount for t in transactions if t.amount > 0 and t.type != "Interest"), 2)
        money_out = round(sum(t.amount for t in transactions if t.amount < 0), 2)
        interest = round(sum(t.amount for t in transactions if t.type == "Interest"), 2)
        if (money_in, money_out, interest) != tuple(round(v, 2) for v in totals[:3]):
            raise ParseError(
                f"{file}: rows add up to in {money_in:+.2f} / out {money_out:+.2f} / interest "
                f"{interest:+.2f}, but the statement totals are {totals[0]:+.2f} / {totals[1]:+.2f} / "
                f"{totals[2]:+.2f}. The PDF layout may have changed."
            )
    return transactions


def _transaction(when: date, desc: list[str], amount: float, holder: str, account: str, file: str) -> Transaction:
    name, how = desc[0], " ".join(desc[1:])
    channel = next((c for c in DUITNOW_CHANNELS if how.lower().startswith(c.lower())), "")
    common = dict(date=when, source=SOURCE, account=account, amount=amount, file=file)

    if channel:
        reference = how[len(channel):].strip()
        to_self = bool(holder) and name.lower() == holder
        return Transaction(
            description=f"{name} - {how}",
            type=channel,
            # DuitNow to/from your own name: your money moving between banks.
            internal=to_self,
            transfer=to_self,
            counterparty=name,
            purpose=purpose_of([reference]),
            **common,
        )
    # Paid with the GX card or a QR code: the name is the shop.
    return Transaction(description=name, type=how, **common)


class GxParser(TextPdfParser):
    name = "gx"
    label = SOURCE
    default_patterns = ["*-statement.pdf"]
    marker = "GX Bank Berhad"  # "-statement.pdf" is a common ending; only claim GX Bank's

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        return parse_text(self.text(name, data, password), file=name)

"""Maybank credit card statements.

Files are named <16-digit card number>_<YYYYMMDD statement date>.pdf. The text
layer is clean, so this reads it with pypdf instead of table extraction.
Transaction lines look like:

    05/07 06/07 GRAB*FOOD KUALA LUMPUR MY        25.40
    10/07 10/07 PAYMENT VIA MBB ONLINE          500.00CR

Charges are money out (negative); CR lines are payments/refunds (positive).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import PurePath

from ..models import Transaction
from .base import ParseError, TextPdfParser

FILENAME_RE = re.compile(r"^(?P<card>\d{16})_(?P<date>\d{8})\.pdf$", re.IGNORECASE)
DATE_PAIR_RE = re.compile(r"^(?P<pdate>\d{2}/\d{2})\s+(?P<tdate>\d{2}/\d{2})\s+(?P<rest>.+)$")
AMOUNT_RE = re.compile(r"([\d,]+\.\d{2})\s*(CR)?\s*$", re.IGNORECASE)
REFERENCE_LINE_RE = re.compile(r"^\d{6,}$")
SKIP_DESC_PATTERNS = [
    re.compile(r"RETAIL INTEREST RATE", re.IGNORECASE),
    re.compile(r"CASH INTEREST RATE", re.IGNORECASE),
]


def resolve_year(ddmm: str, statement_date: date) -> date:
    """Statement lines only carry DD/MM. Nothing on a statement is dated
    after the statement itself, so a January statement's December charges
    belong to the year before."""
    day, month = (int(v) for v in ddmm.split("/"))
    resolved = date(statement_date.year, month, day)
    if resolved > statement_date:
        resolved = date(statement_date.year - 1, month, day)
    return resolved


def parse_text(text: str, statement_date: date, account: str, file: str = "") -> list[Transaction]:
    transactions: list[Transaction] = []
    pending: Transaction | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = DATE_PAIR_RE.match(line)
        if m:
            rest = m.group("rest")
            amount_match = AMOUNT_RE.search(rest)
            if any(p.search(rest) for p in SKIP_DESC_PATTERNS) or not amount_match:
                pending = None
                continue
            amount = float(amount_match.group(1).replace(",", ""))
            is_credit = bool(amount_match.group(2))
            description = re.sub(r"\s{2,}", " ", rest[: amount_match.start()]).strip()
            # Paying off the card moves your own money; it isn't income.
            repayment = is_credit and "PAYMENT" in description.upper()
            pending = Transaction(
                date=resolve_year(m.group("tdate"), statement_date),
                source="Maybank Card",
                account=account,
                description=description,
                amount=amount if is_credit else -amount,
                type="Credit" if is_credit else "Charge",
                internal=repayment,
                transfer=repayment,
                file=file,
            )
            transactions.append(pending)
            continue

        # Reference numbers wrap onto their own line under the transaction.
        if pending is not None and REFERENCE_LINE_RE.match(line):
            pending.reference = f"{pending.reference} {line}".strip()

    return transactions


class MaybankCardParser(TextPdfParser):
    name = "maybank_cc"
    label = "Maybank Card"

    def matches(self, path: PurePath) -> bool:
        if self.name in self.config.patterns:
            return super().matches(path)
        return bool(FILENAME_RE.match(path.name))

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        m = FILENAME_RE.match(name)
        if not m:
            raise ParseError(f"{name}: expected <card number>_<YYYYMMDD>.pdf so the statement year is known")
        statement_date = datetime.strptime(m.group("date"), "%Y%m%d").date()
        account = f"card ...{m.group('card')[-4:]}"
        return parse_text(self.text(name, data, password), statement_date, account, file=name)

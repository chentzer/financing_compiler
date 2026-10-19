"""AEON Credit card statements ("<Month> <YYYY> e-statement.pdf", password
protected: passwords.aeon_credit).

Transaction lines in the text layer look like:

    02 Sep 2026 02 Sep 2026 AEON BIG-JAYA ONE PETALING JAYAMY 7.90
    02 Sep 2026 02 Sep 2026 FPX PAYMENT TRANSFER CR 868.79

posting date, transaction date, merchant (with city and country stuck on),
amount. Each card on the account starts a section with "<16 digits> MR NAME".

User's rule for this card: ignore every CR row (payments to the card,
points redemption, cashback). They're kept as internal rows only so a card
payment from a bank statement can be paired with them and dropped too.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..models import Transaction
from .base import ParseError, TextPdfParser

SOURCE = "AEON Credit"
DATE = r"\d{2} [A-Za-z]{3} \d{4}"
LINE_RE = re.compile(
    rf"^(?P<posted>{DATE}) (?P<date>{DATE}) (?P<desc>.+?)(?P<cr> CR)? (?P<amount>[\d,]+\.\d{{2}})$"
)
CARD_RE = re.compile(r"^(?P<card>\d{16}) (?:MR|MS|MRS|MDM|DR|MISS)?\s*(?P<name>.+)$")
PREVIOUS_RE = re.compile(r"YOUR PREVIOUS STATEMENT BALANCE (?P<amount>[\d,]+\.\d{2})")
CHARGES_RE = re.compile(r"TOTAL CHARGES OF THIS MONTH (?P<amount>[\d,]+\.\d{2})")
CLOSING_RE = re.compile(r"CLOSING BALANCE (?P<amount>[\d,]+\.\d{2})(?P<cr> CR)?")

# Merchant descriptors end with the city and a country code, often glued
# together ("PETALING JAYAMY"). Stripped so the Item reads as the shop name.
CITIES = [
    "PETALING JAYA", "KUALA LUMPUR", "KUALALUMPUR", "SUBANG JAYA", "SHAH ALAM", "PUCHONG", "CYBERJAYA",
    "PUTRAJAYA", "KLANG", "BANGI", "KAJANG", "CHERAS", "AMPANG", "SETIA ALAM", "SEPANG", "SELANGOR",
    "JOHOR BAHRU", "PENANG", "GEORGE TOWN", "IPOH", "MELAKA", "SEREMBAN", "KOTA KINABALU", "KUCHING",
    "SINGAPORE",
]
# A glued country code is only removed right after a known city, so names
# like "ACADEMY" keep their ending.
CITY_RE = re.compile(r"\s+(?:" + "|".join(re.escape(c) for c in CITIES) + r")(?:MY|SG)?$", re.IGNORECASE)
COUNTRY_RE = re.compile(r"\s+(?:MY|SG)$")


def clean_merchant(desc: str) -> str:
    text = re.sub(r"\s{2,}", " ", desc).strip()
    text = COUNTRY_RE.sub("", text)
    text = CITY_RE.sub("", text).strip()
    return text or desc.strip()


def _amount(text: str) -> float:
    return float(text.replace(",", ""))


def parse_text(text: str, file: str = "") -> list[Transaction]:
    transactions: list[Transaction] = []
    account = ""
    for raw in text.splitlines():
        line = raw.strip()
        if m := CARD_RE.match(line):
            account = f"card ...{m.group('card')[-4:]}"
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        amount = _amount(m.group("amount"))
        credit = bool(m.group("cr"))
        desc = m.group("desc").strip()
        transactions.append(
            Transaction(
                date=datetime.strptime(m.group("date"), "%d %b %Y").date(),
                source=SOURCE,
                account=account or "card",
                description=clean_merchant(desc),
                amount=amount if credit else -amount,
                type="Credit" if credit else "Charge",
                # Ignored (user's rule). Payments to the card are the other
                # side of a bank transfer, so they can still be paired.
                internal=credit,
                transfer=credit and "PAYMENT" in desc.upper(),
                note=desc if clean_merchant(desc) != desc else "",
                file=file,
            )
        )

    _check_totals(text, transactions, file)
    return transactions


def _check_totals(text: str, transactions: list[Transaction], file: str) -> None:
    """The statement prints its own totals; a misread line would break them."""
    charges = round(sum(-t.amount for t in transactions if t.amount < 0), 2)
    credits = round(sum(t.amount for t in transactions if t.amount > 0), 2)
    if m := CHARGES_RE.search(text):
        if round(_amount(m.group("amount")), 2) != charges:
            raise ParseError(
                f"{file}: read RM {charges:,.2f} of charges but the statement says "
                f"RM {m.group('amount')}. The PDF layout may have changed."
            )
    prev, closing = PREVIOUS_RE.search(text), CLOSING_RE.search(text)
    if prev and closing:
        expected = round(_amount(prev.group("amount")) + charges - credits, 2)
        stated = _amount(closing.group("amount")) * (-1 if closing.group("cr") else 1)
        if round(stated, 2) != expected:
            raise ParseError(
                f"{file}: closing balance should be RM {expected:,.2f} from the rows read, "
                f"but the statement says RM {stated:,.2f}."
            )


class AeonCreditParser(TextPdfParser):
    name = "aeon_credit"
    label = SOURCE
    default_patterns = ["*e-statement*.pdf"]
    marker = "AEON CREDIT SERVICE"  # "e-statement" is a common name; only claim AEON's

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        return parse_text(self.text(name, data, password), file=name)

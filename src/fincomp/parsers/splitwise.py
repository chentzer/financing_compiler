"""Splitwise group export (CSV: Date, Description, Category, Cost, Currency,
then one balance column per member).

Only your share of each bill is spending, so the trip comes to what
Splitwise says you spent. A member's balance on a row is what they paid
minus their share, so for you (Transaction.reference says which):
- Expense, your balance > 0: you paid it -> your share (Cost - balance),
  "paid"; the remark says the whole bill ("Bbq (you paid 1,629,000.00)").
- Expense, your balance < 0: someone else paid -> your share (-balance), "share".
- Expense, every balance 0: a solo expense, taken as yours -> spending.
- Payments ("X paid You", "You paid X"): not recorded ("settle", internal):
  your share is already counted, so paying back either way isn't spending
  or earnings.
- Payments between other members -> not read.
A bank row that is the same money as a bill you paid (the card charge) or
a payment (the DuitNow) isn't recorded either, so only your share counts
(pipeline.settle_splitwise).

Amounts stay in the group's currency: a row in VND keeps its VND amount
(Transaction.amount) and goes in the VND block of the trip in that currency
(accounts.foreign_currency reads the currency back from the description).
Nothing is converted. Rows in a currency no trip has are left out and
counted in `missing`: the upload goes ahead, the app says to add the trip,
and uploading the file again adds them. Which column is you: the one matching `config.me` (your Google
name in the app; `me = [...]` in config.toml).

Splitwise's categories fill Category where they map to yours (Dining out ->
Food, Taxi -> Transport ...); "General" is left for you.

A row that is also on a bank statement (paid by card, repaid by DuitNow) is
recorded once: see combine.match_splitwise and pipeline.settle_splitwise.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from ..config import Config, currency_code  # noqa: F401 (currency_code: used here and imported from here)
from ..models import Transaction
from .base import ParseError, Parser

HEADER = ["Date", "Description", "Category", "Cost", "Currency"]
SOURCE = "Splitwise"
# Transaction.reference of each kind of Splitwise row ("" = something you paid in full).
PAID, SHARE, SETTLE = "paid", "share", "settle"

CATEGORY_MAP = {
    "dining out": "Food", "groceries": "Food", "liquor": "Food", "food and drink - other": "Food",
    "food and drink": "Food",
    "taxi": "Transport", "bus/train": "Transport", "parking": "Transport", "gas/fuel": "Transport", "car": "Transport",
    "transportation - other": "Transport", "plane": "Transport", "bicycle": "Transport",
    "hotel": "Bills", "rent": "Bills", "electricity": "Bills", "water": "Bills", "tv/phone/internet": "Bills",
    "utilities - other": "Bills", "insurance": "Bills",
    "movies": "Entertainment", "games": "Entertainment", "music": "Entertainment", "sports": "Entertainment",
    "entertainment - other": "Entertainment",
    "clothing": "Shopping", "electronics": "Shopping", "household supplies": "Shopping", "furniture": "Shopping",
    "home - other": "Shopping", "gifts": "Misc",
    "medical expenses": "Health",
    "education": "Self-Development",
}



def _words(name: str) -> set[str]:
    return {w for w in re.split(r"[\s.]+", name.lower()) if w}


def find_me(members: list[str], me: list[str]) -> int:
    """Index of your column: a member whose name has the same words as one
    of `me` (either way round, so "Mei Ling" finds "Tan Mei Ling")."""
    wanted = [_words(m) for m in me if m.strip()]
    hits = [i for i, m in enumerate(members)
            if any(w and (_words(m) <= w or w <= _words(m)) for w in wanted)]
    if len(hits) == 1:
        return hits[0]
    shown = ", ".join(members)
    if not hits:
        raise ParseError(f"Couldn't tell which Splitwise member is you ({shown}). "
                         "Your Google account name should match your Splitwise name.")
    raise ParseError(f"More than one Splitwise member could be you ({shown}).")


def _amount(text: str) -> float:
    try:
        return float(text.replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


class SplitwiseParser(Parser):
    name = "splitwise"
    label = SOURCE
    default_patterns = ["*.csv"]

    def sniff(self, name: str, data: bytes, password: str = "") -> bool:
        return data[:200].decode("utf-8-sig", "ignore").lstrip().startswith(",".join(HEADER))

    def has_trip(self, code: str) -> bool:
        """RM, or a currency some trip has a block for (counted in self.missing if not)."""
        if code == "MYR" or any(currency_code(c) == code for t in self.config.trips for c, _ in t.currencies()):
            return True
        self.missing[code] = self.missing.get(code, 0) + 1
        return False

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        if not rows or rows[0][:5] != HEADER:
            raise ParseError(f"{name}: not a Splitwise export")
        members = [m.strip() for m in rows[0][5:]]
        me = find_me(members, self.config.me)
        group = re.sub(r"_\d{4}-\d{2}-\d{2}_export$", "", name.rsplit(".", 1)[0])  # same for every export

        self.missing: dict[str, int] = {}  # currency no trip has -> rows left out
        out = []
        for r in rows[1:]:
            if len(r) < 5 + len(members) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[0].strip()):
                continue
            desc, category, cost, cur = r[1].strip(), r[2].strip(), _amount(r[3]), r[4].strip()
            if desc == "Total balance" or not cost:
                continue
            balances = [_amount(x) for x in r[5:5 + len(members)]]
            mine = balances[me]
            when = date.fromisoformat(r[0].strip())
            others = [(members[i], b) for i, b in enumerate(balances) if i != me and b]

            code = currency_code(cur)
            if (mine or not any(balances)) and not self.has_trip(code):
                continue  # added when the file is uploaded again, once a trip has this currency

            def add(amount: float, label: str, purpose: str, reference: str, other: str = "", **more) -> None:
                amount = round(amount, 2)  # in `code`: not converted
                out.append(Transaction(
                    date=when, source=SOURCE, account=group, description=f"{label} · {code} {abs(amount):,.2f}",
                    amount=amount, type=category, counterparty=other, purpose=purpose, reference=reference,
                    category="" if reference == SETTLE else CATEGORY_MAP.get(category.lower(), ""), **more))

            if category == "Payment":
                if not mine:
                    continue  # between other members
                other = next((m for m, b in others if (b > 0) == (mine < 0)), others[0][0] if others else "")
                # Never recorded; kept (internal) so paying a friend back can drop its DuitNow.
                add(-mine, desc, "Repayment" if mine < 0 else "Paid back", SETTLE, other, internal=True)
            elif mine > 0:  # you paid: your share; the remark keeps the whole bill (to match the card charge)
                add(mine - cost, f"{desc} (you paid {cost:,.2f})", desc, PAID)
            elif mine < 0:  # someone else paid: your portion
                payer = max(others, key=lambda o: o[1])[0] if others else ""
                add(mine, desc, desc, SHARE, payer)
            elif not any(balances):
                add(-cost, desc, desc, "")  # solo: taken as yours
        return out

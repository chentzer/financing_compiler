"""Splitwise group export (CSV: Date, Description, Category, Cost, Currency,
then one balance column per member).

A member's balance on a row is what they paid minus their share, so for you:
- Expense, your balance > 0: you paid it -> spending of the full Cost.
- Expense, every balance 0: a solo expense, taken as yours -> spending.
- Expense, your balance <= 0 otherwise: someone else paid; your part comes
  in when you pay them back (below) -> not recorded.
- Payment ("X paid You"), your balance < 0: money to you -> earning.
- Payment ("You paid X"), your balance > 0: money from you -> spending.
- Payments between other members -> not recorded.

Amounts are in the group's currency and converted to RM at the rate of the
trip in that currency (Settings > Trips), nearest by date. Rows in RM need
no rate. Which column is you: the one matching `config.me` (your Google
name in the app; `me = [...]` in config.toml).

Splitwise's categories fill Category where they map to yours (Dining out ->
Food, Taxi -> Transport ...); "General" is left for you.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from ..config import Config
from ..models import Transaction
from .base import ParseError, Parser

HEADER = ["Date", "Description", "Category", "Cost", "Currency"]
SOURCE = "Splitwise"

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

# Common names for currencies, as people type them in a trip's settings.
CURRENCY_NAMES = {"YEN": "JPY", "WON": "KRW", "BAHT": "THB", "DONG": "VND", "RUPIAH": "IDR", "YUAN": "CNY",
                  "RMB": "CNY", "RM": "MYR", "RINGGIT": "MYR"}


def currency_code(name: str) -> str:
    n = name.strip().upper()
    return CURRENCY_NAMES.get(n, n)


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

    def rate(self, currency: str, when: date) -> float:
        code = currency_code(currency)
        if code == "MYR":
            return 1.0
        found = [(t, r) for t in self.config.trips for c, r in t.currencies() if currency_code(c) == code]
        if not found:
            raise ParseError(f"Add the trip in {code} (with its rate) in Settings › Trips first.")
        trip, rate = min(found, key=lambda tr: 0 if tr[0].start <= when <= tr[0].end else min(
            abs((when - tr[0].start).days), abs((when - tr[0].end).days)))
        if not rate:
            raise ParseError(f"Set the RM rate for {code} on \"{trip.name}\" in Settings › Trips first.")
        return rate

    def parse_bytes(self, name: str, data: bytes, password: str = "") -> list[Transaction]:
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        if not rows or rows[0][:5] != HEADER:
            raise ParseError(f"{name}: not a Splitwise export")
        members = [m.strip() for m in rows[0][5:]]
        me = find_me(members, self.config.me)
        group = re.sub(r"_\d{4}-\d{2}-\d{2}_export$", "", name.rsplit(".", 1)[0])  # same for every export

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

            if category == "Payment":
                if not mine:
                    continue  # between other members
                other = next((m for m, b in others if (b > 0) == (mine < 0)), others[0][0] if others else "")
                received = mine < 0
                amount = abs(mine)
                purpose = "Repayment" if received else "Paid back"
            else:
                if mine < 0 or (mine == 0 and any(balances)):
                    continue  # someone else paid
                other, received, amount, purpose = "", False, cost, desc

            rm = round(amount * self.rate(cur, when), 2)
            out.append(Transaction(
                date=when, source=SOURCE, account=group,
                description=f"{desc} · {currency_code(cur)} {amount:,.2f}",
                amount=rm if received else -rm, type=category, counterparty=other, purpose=purpose,
                category=CATEGORY_MAP.get(category.lower(), ""),
            ))
        return out

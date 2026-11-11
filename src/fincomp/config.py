from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Dropdown values from Account Template.xlsx.
DEFAULT_CATEGORIES = [
    "Bills", "Shopping", "Food", "Health", "Entertainment", "Transport", "Self-Development", "Misc",
]
DEFAULT_IMPORTANCE = ["Essential", "Have to Have", "Nice to Have", "Courtesy", "Regretted"]

@dataclass
class GoogleConfig:
    # "{year}" is replaced, giving one spreadsheet per year like the old workbooks.
    spreadsheet: str = "{year} Accounts"


@dataclass
class Trip:
    """A trip gets its own tab (like the 2023 "Japan Trip" sheet). Spending
    dated start..end, and bookings matching `match` made before the trip,
    go there instead of the month tabs."""

    name: str
    start: date
    end: date
    currency: str = ""  # e.g. "JPY": a spending block in that currency
    rate: float | None = None  # RM per 1 unit of `currency`
    # More currencies on the same trip (Europe: CHF, then EUR, GBP), each with its rate.
    extra: list[tuple[str, float | None]] = field(default_factory=list)
    match: list[str] = field(default_factory=list)
    link: str = ""  # shown as "Trip Link" in C1
    lead_days: int = 180  # how long before the trip a booking can be

    def currencies(self) -> list[tuple[str, float | None]]:
        """[(currency, RM per 1)] in block order; [] for a trip in RM only."""
        first = [(self.currency, self.rate)] if self.currency else []
        return first + [(c, r) for c, r in self.extra if c]

    def owns(self, when: date, description: str) -> bool:
        if self.start <= when <= self.end:
            return True
        if when > self.end or (self.start - when).days > self.lead_days:
            return False
        text = description.lower()
        return any(m.lower() in text for m in self.match)


@dataclass
class CustomTable:
    """One table on a custom sheet: Date, <label>, Amount (<currency>), Remarks."""

    name: str
    currency: str = "RM"
    label: str = "Item"  # the second column, e.g. "Person" for ang pao


@dataclass
class CustomSheet:
    """A tab of your own in a year's spreadsheet (e.g. "Chinese New Year"
    with ang pao received in RM and SGD). Its RM tables can count towards
    the Year End Summary."""

    name: str
    year: int
    counts: str = ""  # "earnings", "spending" or "" (not counted)
    tables: list[CustomTable] = field(default_factory=list)
    # What it's for, to group sheets in the app ("Chinese New Year", "Investments": its own tab).
    category: str = ""


def _list(v) -> list[str]:
    """"CHF, EUR" or ["CHF", "EUR"] -> ["CHF", "EUR"]."""
    if v is None or v == "":
        return []
    items = v if isinstance(v, list) else str(v).split(",")
    return [str(x).strip() for x in items if str(x).strip()]


def _rates(v) -> list[float | None]:
    if v is None or v == "":
        return []
    items = v if isinstance(v, list) else str(v).split(",")
    out = []
    for x in items:
        try:
            out.append(float(x) if str(x).strip() else None)
        except ValueError:
            out.append(None)
    return out


@dataclass
class Config:
    transfer_window_days: int = 3
    passwords: dict[str, str] = field(default_factory=dict)
    patterns: dict[str, list[str]] = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    importance: list[str] = field(default_factory=lambda: list(DEFAULT_IMPORTANCE))
    google: GoogleConfig = field(default_factory=GoogleConfig)
    trips: list[Trip] = field(default_factory=list)
    sheets: list[CustomSheet] = field(default_factory=list)  # your own tabs (Settings › Sheets)
    # Money from other people goes under Earnings (rule 2). Money moving
    # between your own accounts is never recorded either way.
    record_earnings: bool = True
    # Payees that are really your own money moving (rule 1): paying your
    # credit card bill, topping up an investment account.
    own_payees: list[str] = field(default_factory=lambda: ["AEON CREDIT SERVICE"])
    # Row keys the user marked "not mine" in the app (Settings › Removed).
    removed: set[str] = field(default_factory=set)
    # Row keys whose card you skipped: kept as recorded, never asked about again.
    reviewed: set[str] = field(default_factory=set)
    # How people show in Remarks: {"TAN MEI LING": "Mei Ling"}. Unlisted names
    # are shortened automatically.
    people: dict[str, str] = field(default_factory=dict)
    # Your own name(s), to find your column in a Splitwise export. The app
    # passes your Google account name.
    me: list[str] = field(default_factory=list)

    def password(self, parser_name: str) -> str:
        return self.passwords.get(parser_name, "") or ""

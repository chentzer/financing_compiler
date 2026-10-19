from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Dropdown values from Account Template.xlsx.
DEFAULT_CATEGORIES = [
    "Bills", "Shopping", "Food", "Health", "Entertainment", "Transport", "Self-Development", "Misc",
]
DEFAULT_IMPORTANCE = ["Essential", "Have to Have", "Nice to Have", "Courtesy", "Regretted"]

CONFIG_HOME = Path.home() / ".config" / "fincomp"


@dataclass
class GoogleConfig:
    # "{year}" is replaced, giving one spreadsheet per year like the old workbooks.
    spreadsheet: str = "{year} Accounts"
    folder_id: str = ""  # Drive folder for new spreadsheets; blank = My Drive
    credentials: Path = CONFIG_HOME / "credentials.json"  # OAuth client from Google Cloud
    token: Path = CONFIG_HOME / "token.json"  # written after the first sign-in
    upload: bool = False  # upload on every run without --upload


@dataclass
class Trip:
    """A trip gets its own tab (like the 2023 "Japan Trip" sheet). Spending
    dated start..end, and bookings matching `match` made before the trip,
    go there instead of the month tabs."""

    name: str
    start: date
    end: date
    currency: str = ""  # e.g. "Yen": adds the cash-in-that-currency blocks
    rate: float | None = None  # RM per 1 unit; blank = worked out from "Money Exchange" rows
    match: list[str] = field(default_factory=list)
    link: str = ""  # shown as "Trip Link" in C1
    lead_days: int = 180  # how long before the trip a booking can be

    def owns(self, when: date, description: str) -> bool:
        if self.start <= when <= self.end:
            return True
        if when > self.end or (self.start - when).days > self.lead_days:
            return False
        text = description.lower()
        return any(m.lower() in text for m in self.match)


def _date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _trip(raw: dict) -> Trip:
    match = raw.get("match", [])
    return Trip(
        name=str(raw["name"]),
        start=_date(raw["start"]),
        end=_date(raw["end"]),
        currency=str(raw.get("currency", "")),
        rate=float(raw["rate"]) if raw.get("rate") else None,
        match=[match] if isinstance(match, str) else list(match),
        link=str(raw.get("link", "")),
        lead_days=int(raw.get("lead_days", 180)),
    )


@dataclass
class Config:
    transfer_window_days: int = 3
    passwords: dict[str, str] = field(default_factory=dict)
    patterns: dict[str, list[str]] = field(default_factory=dict)
    csv: list[dict] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    importance: list[str] = field(default_factory=lambda: list(DEFAULT_IMPORTANCE))
    google: GoogleConfig = field(default_factory=GoogleConfig)
    trips: list[Trip] = field(default_factory=list)
    # Money from other people goes under Earnings (rule 2). Money moving
    # between your own accounts is never recorded either way.
    record_earnings: bool = True
    # Payees that are really your own money moving (rule 1): paying your
    # credit card bill, topping up an investment account.
    own_payees: list[str] = field(default_factory=lambda: ["AEON CREDIT SERVICE"])
    # Row keys the user marked "not mine" in the app (Settings › Removed).
    removed: set[str] = field(default_factory=set)
    # How people show in Remarks: {"TAN MEI LING": "Mei Ling"}. Unlisted names
    # are shortened automatically.
    people: dict[str, str] = field(default_factory=dict)
    # Your answers from the To Update cards, so each is asked only once.
    # Outside the repo: it's personal data.
    answers: Path = CONFIG_HOME / "answers.json"

    def password(self, parser_name: str) -> str:
        return self.passwords.get(parser_name, "") or ""


def _google(raw: dict) -> GoogleConfig:
    g = GoogleConfig()
    for key in ("spreadsheet", "folder_id"):
        if key in raw:
            setattr(g, key, str(raw[key]))
    for key in ("credentials", "token"):
        if raw.get(key):
            setattr(g, key, Path(raw[key]).expanduser())
    g.upload = bool(raw.get("upload", False))
    return g


def load_config(path: Path | None) -> Config:
    if path is None or not path.exists():
        return Config()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return Config(
        transfer_window_days=int(raw.get("transfer_window_days", 3)),
        passwords=dict(raw.get("passwords", {})),
        patterns={k: list(v) for k, v in raw.get("patterns", {}).items()},
        csv=list(raw.get("csv", [])),
        rules=list(raw.get("rules", [])),
        categories=list(raw.get("categories", DEFAULT_CATEGORIES)),
        importance=list(raw.get("importance", DEFAULT_IMPORTANCE)),
        google=_google(raw.get("google", {})),
        trips=[_trip(t) for t in raw.get("trips", [])],
        record_earnings=bool(raw.get("record_earnings", True)),
        own_payees=list(raw.get("own_payees", ["AEON CREDIT SERVICE"])),
        people={k.upper(): str(v) for k, v in raw.get("people", {}).items()},
        answers=Path(raw["answers"]).expanduser() if raw.get("answers") else CONFIG_HOME / "answers.json",
    )

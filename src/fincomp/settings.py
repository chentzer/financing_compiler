"""The "fincomp Settings" spreadsheet in the user's Drive: what config.toml
holds for the CLI, as tabs both the website and the phone app read and
edit. Also the hidden Ledger tab (every parsed transaction, so statements
uploaded one at a time are still deduped and paired across banks).

PDF passwords are *not* here: they live in the Drive App Data folder
(passwords.vault.json), encrypted with the user's PIN (vault.py).

Pure functions: tab values in, Config out, and back. Write these tabs with
valueInputOption RAW so text stays text (dates, "+60..." numbers, "=").
"""

from __future__ import annotations

from datetime import date

from .config import Config, Trip
from .models import Transaction

SETTINGS_TITLE = "fincomp Settings"
PASSWORDS_FILE = "passwords.vault.json"  # in the Drive App Data folder, encrypted (vault.py)

RULES = "Rules"
PEOPLE = "People"
TRIPS = "Trips"
OWN_PAYEES = "Own payees"
LISTS = "Lists"
REMOVED = "Removed"
LEDGER = "Ledger"
TABS = [RULES, PEOPLE, TRIPS, OWN_PAYEES, LISTS, REMOVED, LEDGER]
HIDDEN = {LEDGER}

HEADERS = {
    RULES: ["Match (any of, separated by |)", "Category", "Importance", "Item", "Trip", "Skip", "Source", "Regex"],
    PEOPLE: ["Name on statement", "Show as"],
    TRIPS: ["Name", "Start (YYYY-MM-DD)", "End (YYYY-MM-DD)", "Currency", "Rate (RM per 1)", "Match (|)", "Link",
            "Lead days"],
    OWN_PAYEES: ["Payee (your own money, e.g. your credit card)"],
    LISTS: ["Categories", "Importance"],
    REMOVED: ["Key", "Date", "Amount (RM)", "Statement"],
    LEDGER: Transaction.columns(),
}
SEP = " | "


def _s(row: list, i: int) -> str:
    return str(row[i]).strip() if i < len(row) and row[i] is not None else ""


def _yes(v) -> bool:
    return str(v).strip().upper() in ("TRUE", "YES", "Y", "1")


def _body(values: dict[str, list[list]], tab: str) -> list[list]:
    """Rows under the header, skipping blank ones."""
    return [r for r in values.get(tab, [])[1:] if any(str(c).strip() for c in r)]


# ---- Config <-> tabs ----------------------------------------------------------


def config_from_tabs(values: dict[str, list[list]], passwords: dict[str, str] | None = None,
                     base: Config | None = None) -> Config:
    config = base or Config()
    rules = []
    for r in _body(values, RULES):
        rule: dict = {}
        if match := _s(r, 0):
            parts = [m.strip() for m in match.split("|") if m.strip()]
            rule["match"] = parts[0] if len(parts) == 1 else parts
        for i, key in ((1, "category"), (2, "importance"), (3, "item"), (4, "trip"), (6, "source"), (7, "regex")):
            if v := _s(r, i):
                rule[key] = v
        if _yes(_s(r, 5)):
            rule["skip"] = True
        if rule.get("match") or rule.get("regex"):
            rules.append(rule)
    config.rules = rules

    config.people = {_s(r, 0).upper(): _s(r, 1) for r in _body(values, PEOPLE) if _s(r, 0) and _s(r, 1)}

    trips = []
    for r in _body(values, TRIPS):
        if not (_s(r, 0) and _s(r, 1) and _s(r, 2)):
            continue
        trips.append(Trip(
            name=_s(r, 0), start=date.fromisoformat(_s(r, 1)), end=date.fromisoformat(_s(r, 2)),
            currency=_s(r, 3), rate=float(_s(r, 4)) if _s(r, 4) else None,
            match=[m.strip() for m in _s(r, 5).split("|") if m.strip()], link=_s(r, 6),
            lead_days=int(_s(r, 7)) if _s(r, 7) else 180,
        ))
    config.trips = trips

    payees = [_s(r, 0) for r in _body(values, OWN_PAYEES) if _s(r, 0)]
    if OWN_PAYEES in values:
        config.own_payees = payees
    lists = _body(values, LISTS)
    if cats := [_s(r, 0) for r in lists if _s(r, 0)]:
        config.categories = cats
    if imps := [_s(r, 1) for r in lists if _s(r, 1)]:
        config.importance = imps
    config.removed = {_s(r, 0) for r in _body(values, REMOVED) if _s(r, 0)}
    if passwords is not None:
        config.passwords = dict(passwords)
    return config


def tabs_from_config(config: Config) -> dict[str, list[list]]:
    """Header + rows for every tab except Ledger and Removed (those are
    written as the app goes)."""
    rules = []
    for r in config.rules:
        match = r.get("match", "")
        rules.append([
            SEP.join(match) if isinstance(match, list) else match,
            r.get("category", ""), r.get("importance", ""), r.get("item", ""), r.get("trip", ""),
            "TRUE" if r.get("skip") else "", r.get("source", ""), r.get("regex", ""),
        ])
    trips = [
        [t.name, t.start.isoformat(), t.end.isoformat(), t.currency, "" if t.rate is None else t.rate,
         SEP.join(t.match), t.link, t.lead_days]
        for t in config.trips
    ]
    n = max(len(config.categories), len(config.importance))
    lists = [[(config.categories + [""] * n)[i], (config.importance + [""] * n)[i]] for i in range(n)]
    return {
        RULES: [HEADERS[RULES], *rules],
        PEOPLE: [HEADERS[PEOPLE], *([k, v] for k, v in config.people.items())],
        TRIPS: [HEADERS[TRIPS], *trips],
        OWN_PAYEES: [HEADERS[OWN_PAYEES], *([p] for p in config.own_payees)],
        LISTS: [HEADERS[LISTS], *lists],
    }


def rule_row(rule: dict) -> list:
    """One Rules row, for "Same for every … from now on" in the app."""
    return tabs_from_config(Config(rules=[rule]))[RULES][1]


def removed_row(key: str, when: str, amount: float, statement: str) -> list:
    return [key, when, amount, statement]


# ---- Ledger ---------------------------------------------------------------------


def ledger_rows(transactions: list[Transaction]) -> list[list]:
    """Header + one row per transaction, exactly as parsed."""
    cols = Transaction.columns()
    out = [cols]
    for t in transactions:
        row = []
        for c in cols:
            v = getattr(t, c)
            row.append(v.isoformat() if isinstance(v, date) else ("TRUE" if v is True else "" if v is False else v))
        out.append(row)
    return out


def ledger_from_rows(rows: list[list]) -> list[Transaction]:
    if not rows:
        return []
    cols = [str(c) for c in rows[0]]
    out = []
    for r in rows[1:]:
        rec = {c: (r[i] if i < len(r) else "") for i, c in enumerate(cols)}
        if not rec.get("date"):
            continue
        out.append(Transaction(
            date=date.fromisoformat(str(rec["date"])[:10]),
            source=str(rec.get("source", "")), account=str(rec.get("account", "")),
            description=str(rec.get("description", "")), amount=float(rec.get("amount") or 0),
            type=str(rec.get("type", "")), reference=str(rec.get("reference", "")),
            internal=_yes(rec.get("internal", "")), transfer=_yes(rec.get("transfer", "")),
            counterparty=str(rec.get("counterparty", "")), purpose=str(rec.get("purpose", "")),
            note=str(rec.get("note", "")), category=str(rec.get("category", "")), file=str(rec.get("file", "")),
        ))
    return out

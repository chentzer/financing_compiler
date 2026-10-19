"""Turn the combined ledger into the yearly accounts workbook: the layout
of the user's Account Template.xlsx plus trip tabs like "Japan Trip" in
2023 Accounts.xlsx.

Month tab ("January 2026"):
  A-F  Spendings: Date, Item, Category, Amount (RM), Importance, Remarks
  G    hidden key that lets re-runs recognise rows already uploaded
  H-I  spending by Category      K-L  spending by Importance
  N-Q  Earnings: Date, Item, Amount (RM), Remarks
  R    hidden key
  S-T  Earnings, Spendings, Trips (trips that ended this month), and
       Final in T6: last month's Final + earnings - spending - trips

Trip tab ("Japan Trip"), data from row 4:
  A-F  RM spending (bookings, card charges abroad)     G hidden key
  H-M  cash spending in the trip currency (typed by hand)
  O-P  summary, trip total in P8
  Q-T  trip currency received: money exchange, gifts, repayments (by hand)

The template used pivot tables for the summaries. They don't survive a trip
to Google Sheets and need refreshing, so they are SUMIF formulas instead.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .config import Config, Trip
from .models import Transaction

FIRST_ROW = 3  # month tabs: rows 1-2 are headers
TRIP_FIRST_ROW = 4  # trip tabs: title in row 1, headers in row 3
XLSX_LAST_ROW = 2000  # bounded ranges for Excel; Sheets gets open-ended ones

SPEND_HEADERS = ["Date", "Item", "Category", "Amount (RM)", "Importance", "Remarks"]
EARN_HEADERS = ["Date", "Item", "Amount (RM)", "Remarks"]
TRIPS_CELL = "T5"
FINAL_CELL = "T6"
TRIP_TOTAL_CELL = "P8"
MONEY_EXCHANGE = "Money Exchange"  # Item name that marks RM -> trip currency
YEAR_SUMMARY = "Year End Summary"


@dataclass
class AccountRow:
    kind: str  # "spend" or "earn"
    date: date
    item: str
    amount: float  # always positive, as in the template
    remarks: str
    key: str
    category: str = ""
    importance: str = ""
    trip: str = ""  # trip name when this spending belongs on a trip tab
    # What the user still has to fill in: "purpose" (the Item is only
    # "Transfer"/"QR payment") and/or "category". Not written to the sheet.
    needs: tuple[str, ...] = ()
    source: str = ""
    statement: str = ""  # the raw statement description, shown on the card
    counterparty: str = ""  # the person, as on the statement; "" for a shop

    def values(self) -> list:
        if self.kind == "spend":
            return [self.date, self.item, self.category, self.amount, self.importance, self.remarks, self.key]
        return [self.date, self.item, self.amount, self.remarks, self.key]


def month_title(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def parse_month_title(title: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"([A-Za-z]+) (\d{4})", title.strip())
    if not m or m.group(1) not in calendar.month_name[1:]:
        return None
    return int(m.group(2)), list(calendar.month_name).index(m.group(1))


# ---- rows ---------------------------------------------------------------


def _rule_matches(rule: dict, t: Transaction) -> bool:
    if rule.get("source") and rule["source"].lower() != t.source.lower():
        return False
    text = f"{t.description} {t.type}"
    if rule.get("regex"):
        return re.search(rule["regex"], text, re.IGNORECASE) is not None
    if rule.get("match"):
        needles = rule["match"] if isinstance(rule["match"], list) else [rule["match"]]
        return any(n.lower() in text.lower() for n in needles)
    return False


def find_rule(rules: list[dict], t: Transaction) -> dict:
    """First matching rule wins."""
    return next((r for r in rules if _rule_matches(r, t)), {})


def find_trip(trips: list[Trip], t: Transaction, rule: dict) -> str:
    if t.amount >= 0:
        return ""  # money in stays on the month tab
    if rule.get("trip"):
        return rule["trip"]
    return next((trip.name for trip in trips if trip.owns(t.date, t.description)), "")


NAME_JOINERS = {"BIN", "BINTI", "A/L", "A/P", "S/O", "D/O"}
COMPANY_RE = re.compile(
    r"[()&\d]|\b(SDN|SD|BHD|BERHAD|ENTERPRISE|TRADING|SERVICES?|HOLDINGS|GROUP|PLT|LTD|INC|CORP|BANK|INSURANCE)\b",
    re.IGNORECASE,
)


def short_name(name: str, people: dict[str, str]) -> str:
    """How a person shows in Remarks: "TAN MEI LING" -> "Mei Ling".

    [people] in config.toml wins. Otherwise a three-part Chinese name drops
    the surname, a Malay or Indian name keeps the part before bin/binti/a/l,
    and anything else is just title-cased."""
    if name.upper() in people:
        return people[name.upper()]
    words = name.split()
    upper = [w.upper() for w in words]
    if COMPANY_RE.search(name):
        return name.title()  # "SOME EMPLOYER (MALAYSIA) SD" stays whole
    for joiner in NAME_JOINERS:
        if joiner in upper[1:]:
            return " ".join(words[: upper.index(joiner)]).title()
    if len(words) == 3:
        return " ".join(words[1:]).title()
    return name.title()


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _keyed(transactions: list[Transaction]) -> list[tuple[str, Transaction]]:
    seen: Counter = Counter()
    out = []
    for t in sorted(transactions, key=lambda t: t.date):
        # Identical rows (two RM5 coffees on one day) need distinct keys.
        ident = f"{t.source}|{t.account}|{t.date}|{t.description}|{t.amount:.2f}"
        seen[ident] += 1
        out.append((hashlib.sha1(f"{ident}|{seen[ident]}".encode()).hexdigest()[:12], t))
    return out


def _classify(transactions: list[Transaction], config: Config, answers: dict[str, dict]):
    """Yield (key, transaction, rule, answer, remarks) for every
    transaction that belongs in the accounts.

    The recording rules:
      1. money moving between your own accounts is ignored (internal);
      2. only your spending, and money in from other people, is recorded;
      3. a row whose purpose the statement doesn't say is still recorded,
         with what the statement gives, and gets a To Update card.
    """
    # Merchants you told fincomp to remember while reviewing.
    rules = config.rules + answers.get("_rules", [])
    for key, t in _keyed(transactions):
        if t.internal or t.amount == 0:
            continue
        if t.amount > 0 and not config.record_earnings:
            continue
        rule = find_rule(rules, t)
        answer = answers.get(key, {})
        if rule.get("skip") or answer.get("skip") or key in config.removed:
            continue
        if t.counterparty:
            person = short_name(t.counterparty, config.people)
            remarks = f"From {person}" if t.amount > 0 else f"To {person}"
        else:
            remarks = t.source
        yield key, t, rule, answer, remarks


def build_rows(
    transactions: list[Transaction], config: Config, answers: dict[str, dict] | None = None
) -> list[AccountRow]:
    """Rows for the accounts: everything that isn't excluded (rules 1-2).
    Rows the statement doesn't explain go in with what it does say, e.g.
    Item "Transfer", Remarks "From Siew Wen", Category blank."""
    rows = []
    for key, t, rule, answer, remarks in _classify(transactions, config, answers or {}):
        category = answer.get("category") or rule.get("category", "")
        importance = answer.get("importance") or rule.get("importance", "")
        item = answer.get("item") or rule.get("item") or _sentence(t.purpose) or _fallback_item(t)
        kind = "earn" if t.amount > 0 else "spend"
        category = category if category in config.categories else ""
        needs: list[str] = []
        if not answer.get("reviewed"):  # you've seen its card: don't ask again
            if t.counterparty and not t.purpose and not rule.get("item") and not answer.get("item"):
                needs.append("purpose")
            if kind == "spend" and not category:
                needs.append("category")
        rows.append(
            AccountRow(
                kind=kind,
                date=t.date,
                item=item,
                amount=round(abs(t.amount), 2),
                remarks=answer.get("remarks") or rule.get("remarks") or remarks,
                key=key,
                category=category,
                importance=importance if importance in config.importance else "",
                trip=find_trip(config.trips, t, rule),
                needs=tuple(needs),
                source=t.source,
                statement=t.description,
                counterparty=t.counterparty,
            )
        )
    return rows


def needs_update(rows: list[AccountRow]) -> list[AccountRow]:
    return [r for r in rows if r.needs]


TO_UPDATE = "To Update"
TO_UPDATE_HEADERS = ["Date", "Amount (RM)", "Who / where", "Statement", "Recorded as", "Needs", "Tab", "Key"]


def to_update_table(tabs: list["Tab"], resolved: set[str] = frozenset()) -> list[list]:
    """The "To Update" tab: one line per recorded row still missing
    something, with the tab it's in. `resolved` are keys you've already fixed
    by editing the month tab directly."""
    labels = {"purpose": "what it was for", "category": "Category"}
    table = [TO_UPDATE_HEADERS]
    for tab in tabs:
        for r in tab.rows:
            if r.needs and r.key not in resolved:
                table.append([
                    r.date, r.amount if r.kind == "earn" else -r.amount, r.remarks, r.statement,
                    r.item, ", ".join(labels[n] for n in r.needs), tab.title, r.key,
                ])
    if len(table) == 1:
        table.append(["Nothing to update."] + [""] * (len(TO_UPDATE_HEADERS) - 1))
    return table


def _fallback_item(t: Transaction) -> str:
    """Item when the statement gives no purpose: the shop name for a card
    charge, or how the money moved for a person ("Transfer", "QR payment");
    who it was is already in Remarks."""
    if not t.counterparty:
        return t.description
    return "QR payment" if "QR" in t.type.upper() else "Transfer"


def new_rows(rows: list[AccountRow], existing_keys: set[str]) -> list[AccountRow]:
    """Rows not uploaded yet. Rows already in the sheet are left alone so
    the Category/Importance/Item you edited there are kept."""
    return [r for r in rows if r.key not in existing_keys]


# ---- tab plan -----------------------------------------------------------


@dataclass
class Tab:
    title: str
    kind: str  # "month" or "trip"
    order: tuple  # months and trips interleave: a trip sits after its start month
    rows: list[AccountRow] = field(default_factory=list)
    trip: Trip | None = None

    @property
    def first_row(self) -> int:
        return TRIP_FIRST_ROW if self.kind == "trip" else FIRST_ROW


def _month_order(year: int, month: int) -> tuple:
    return (year, month, 0, "")


def tab_order(title: str, trips: list[Trip]) -> tuple | None:
    """Sort key for a tab title, or None for tabs fincomp doesn't manage."""
    if ym := parse_month_title(title):
        return _month_order(*ym)
    for trip in trips:
        if trip.name == title:
            return (trip.start.year, trip.start.month, 1, trip.name)
    return None


def deduction_month(trip: Trip) -> tuple[int, int]:
    """The month whose Final pays for the trip: the month it ends, kept in
    the trip's own year so it lands in the same spreadsheet."""
    if trip.end.year != trip.start.year:
        return trip.start.year, 12
    return trip.end.year, trip.end.month


def plan(rows: list[AccountRow], config: Config) -> dict[int, list[Tab]]:
    """Tabs per year, in workbook order."""
    trips = {t.name: t for t in config.trips}
    tabs: dict[str, Tab] = {}

    def month_tab(y: int, m: int) -> Tab:
        title = month_title(y, m)
        return tabs.setdefault(title, Tab(title, "month", _month_order(y, m)))

    for r in rows:
        trip = trips.get(r.trip)
        if trip is None:
            if r.trip:
                r.trip = ""  # a rule named a trip that isn't configured
            month_tab(r.date.year, r.date.month).rows.append(r)
            continue
        tab = tabs.setdefault(trip.name, Tab(trip.name, "trip", tab_order(trip.name, config.trips), trip=trip))
        tab.rows.append(r)
        month_tab(*deduction_month(trip))  # must exist to subtract the trip

    by_year: dict[int, list[Tab]] = {}
    for tab in sorted(tabs.values(), key=lambda t: t.order):
        by_year.setdefault(tab.order[0], []).append(tab)
    return by_year


# ---- layout -------------------------------------------------------------


def _rng(col: str, first: int, open_ended: bool) -> str:
    return f"${col}${first}:${col}" + ("" if open_ended else f"${XLSX_LAST_ROW}")


def quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def month_layout(config: Config, open_ended: bool) -> dict[str, object]:
    """Header and summary cells of a month tab, as {cell: value or formula}.
    T5 and T6 depend on the other tabs; see month_links()."""
    cells: dict[str, object] = {"A1": "Spendings", "N1": "Earnings"}
    for col, h in zip("ABCDEF", SPEND_HEADERS):
        cells[f"{col}2"] = h
    for col, h in zip("NOPQ", EARN_HEADERS):
        cells[f"{col}2"] = h
    cells["G2"] = "Key"
    cells["R2"] = "Key"
    amounts = _rng("D", FIRST_ROW, open_ended)

    def block(label_col: str, value_col: str, data_col: str, heading: str, labels: list[str]) -> None:
        cells[f"{label_col}2"] = heading
        cells[f"{value_col}2"] = "Spent (RM)"
        crit = _rng(data_col, FIRST_ROW, open_ended)
        row = FIRST_ROW
        for label in labels:
            cells[f"{label_col}{row}"] = label
            cells[f"{value_col}{row}"] = f'=SUMIF({crit},"{label}",{amounts})'
            row += 1
        cells[f"{label_col}{row}"] = "Not set"
        cells[f"{value_col}{row}"] = f'=SUMIFS({amounts},{crit},"",{amounts},"<>")'
        cells[f"{label_col}{row + 1}"] = "Total"
        cells[f"{value_col}{row + 1}"] = f"=SUM({amounts})"

    block("H", "I", "C", "Category", config.categories)
    block("K", "L", "E", "Importance", config.importance)

    cells["S2"] = "Summary"
    cells["T2"] = "RM"
    cells["S3"] = "Earnings"
    cells["T3"] = f"=SUM({_rng('P', FIRST_ROW, open_ended)})"
    cells["S4"] = "Spendings"
    cells["T4"] = f"=SUM({amounts})"
    cells["S5"] = "Trips"
    cells["S6"] = "Final"
    return cells


def trip_layout(trip: Trip, config: Config, open_ended: bool) -> dict[str, object]:
    r = TRIP_FIRST_ROW
    cells: dict[str, object] = {"A1": trip.name}
    if trip.link:
        cells["C1"] = f'=HYPERLINK("{trip.link}","Trip Link")'
    for col, h in zip("ABCDEF", SPEND_HEADERS):
        cells[f"{col}3"] = h
    cells["G3"] = "Key"

    rm = _rng("D", r, open_ended)
    items = _rng("B", r, open_ended)
    cells["O3"] = "Summary"
    cells["P3"] = "Amount"
    cells["O4"] = "Spent in RM"
    cells["P4"] = f'=SUM({rm})-SUMIF({items},"{MONEY_EXCHANGE}",{rm})'

    cur = trip.currency
    if not cur:
        cells["O8"] = "Trip Total (RM)"
        cells[TRIP_TOTAL_CELL] = "=P4"
        return cells

    for col, h in zip("HIJKLM", ["Date", "Item", "Category", f"Amount ({cur})", "Importance", "Remarks"]):
        cells[f"{col}3"] = h
    for col, h in zip("QRST", ["Date", "Item", f"Amount ({cur})", "Remarks"]):
        cells[f"{col}3"] = h
    cells["H2"] = f"Cash spending in {cur} (fill in yourself)"
    cells["Q2"] = f"{cur} received: money exchange, gifts, repayments"

    received = _rng("S", r, open_ended)
    received_items = _rng("R", r, open_ended)
    cells["O5"] = f"Spent in {cur}"
    cells["P5"] = f"=SUM({_rng('K', r, open_ended)})"
    cells["O6"] = f"RM per 1 {cur}"
    if trip.rate:
        cells["P6"] = trip.rate
    else:
        # Worked out from what the exchange cost and what it gave you.
        cells["P6"] = (
            f'=IFERROR(SUMIF({items},"{MONEY_EXCHANGE}",{rm})'
            f'/SUMIF({received_items},"{MONEY_EXCHANGE}",{received}),0)'
        )
    cells["O7"] = f"{cur} spending in RM"
    cells["P7"] = "=P5*P6"
    cells["O8"] = "Trip Total (RM)"
    cells[TRIP_TOTAL_CELL] = "=P4+P7"
    cells["O10"] = f"{cur} received"
    cells["P10"] = f"=SUM({received})"
    cells["O11"] = f"{cur} left (expected)"
    cells["P11"] = "=P10-P5"
    cells["O12"] = f"{cur} left (counted)"
    cells["O13"] = "Unaccounted"
    cells["P13"] = '=IF(P12="","",P12-P11)'
    return cells


def month_links(month_titles: list[str], trips: list[Trip], trip_titles: set[str]) -> dict[str, dict[str, str]]:
    """T5 (trips paid this month) and T6 (Final) for every month tab. Written
    on every run because tabs and trips can be added later."""
    by_month: dict[tuple[int, int], list[str]] = {}
    for trip in trips:
        if trip.name in trip_titles:
            by_month.setdefault(deduction_month(trip), []).append(trip.name)

    ordered = sorted(month_titles, key=parse_month_title)
    out = {}
    for i, title in enumerate(ordered):
        paid = by_month.get(parse_month_title(title), [])
        trips_formula = "=" + "+".join(f"{quote(t)}!{TRIP_TOTAL_CELL}" for t in paid) if paid else 0
        carried = f"{quote(ordered[i - 1])}!{FINAL_CELL}+" if i else ""
        out[title] = {TRIPS_CELL: trips_formula, FINAL_CELL: f"={carried}T3-T4-T5"}
    return out


def year_summary_cells(month_titles: list[str], trip_titles: list[str]) -> dict[str, object]:
    if not month_titles:
        return {}
    months = sorted(month_titles, key=parse_month_title)
    earnings = "+".join(f"{quote(t)}!T3" for t in months)
    spending = "+".join(f"{quote(t)}!T4" for t in months)
    trips = "+".join(f"{quote(t)}!{TRIP_TOTAL_CELL}" for t in trip_titles) or "0"
    return {
        "A1": "Total Earnings", "B1": f"={earnings}",
        "A2": "Total Spending", "B2": f"={spending}+B4",
        "A3": "Difference", "B3": "=B1-B2",
        "A4": "of which Trips", "B4": f"={trips}",
    }

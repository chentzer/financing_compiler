"""Turn the combined ledger into the yearly accounts workbook: the layout
of the user's Account Template.xlsx plus trip tabs like "Japan Trip" in
2023 Accounts.xlsx.

Month tab ("January 2026"), a blank column between sections:
  A-G  Spendings: Date, Item, Category, Amount (RM), Importance, Source, Remarks
  H    hidden key that lets re-runs recognise rows already uploaded
  J-K  spending by Category      M-N  spending by Importance
  P-T  Earnings: Date, Item, Amount (RM), Source, Remarks
  U    hidden key
  W-X  Earnings, Spendings, Trips (trips that ended this month), and
       Final in X6: last month's Final + earnings - spending - trips
Source is the bank or wallet; Remarks starts as the statement's own text
and is yours to overwrite.

Trip tab ("Japan Trip"), data from row 4, like the 2025 trip sheets:
  A-G  RM spending (bookings, card charges abroad)     H hidden key
  J-M  paid back to you (RM), e.g. friends' share       N hidden key
  P-Q  summary; trip total in Q4 = RM spent + each currency x its rate
       - paid back
  S-X  spending in the first currency, then one block of 6 per currency
       (a blank column between), then money received in other currencies
       (Date, Item, Currency, Amount, Remarks)

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

SPEND_HEADERS = ["Date", "Item", "Category", "Amount (RM)", "Importance", "Source", "Remarks"]
EARN_HEADERS = ["Date", "Item", "Amount (RM)", "Source", "Remarks"]
CASH_HEADERS = ["Date", "Item", "Category", "Amount", "Importance", "Remarks"]  # Amount (<currency>)
# Month tab columns.
SPEND_COLS, SPEND_KEY = "ABCDEFG", "H"
CAT_COLS, IMP_COLS = "JK", "MN"
EARN_COLS, EARN_KEY = "PQRST", "U"
SUMMARY_COLS = "WX"
EARNINGS_CELL, SPENDINGS_CELL, TRIPS_CELL, FINAL_CELL = "X3", "X4", "X5", "X6"
# Trip tab columns (the 2025 trip sheets' way: what friends paid you back
# comes off the trip). Currency blocks start at S, one per currency.
PAID_COLS, PAID_KEY = "JKLM", "N"
PAID_HEADERS = ["Date", "From", "Amount (RM)", "Remarks"]
TRIP_SUMMARY_COLS = "PQ"
TRIP_TOTAL_CELL = "Q4"
CURRENCY_START = 18  # S
RECEIVED_HEADERS = ["Date", "Item", "Currency", "Amount", "Remarks"]
# Light header fills per section.
COLOURS = {
    "spend": {"red": 0.99, "green": 0.89, "blue": 0.88},
    "earn": {"red": 0.86, "green": 0.96, "blue": 0.88},
    "summary": {"red": 0.86, "green": 0.92, "blue": 0.99},
    "final": {"red": 1.0, "green": 0.94, "blue": 0.75},
    "cash": {"red": 0.93, "green": 0.9, "blue": 0.99},
}
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
    who: str = ""  # "To Jane Tan" or the shop: shown on the To Update card
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
            return [self.date, self.item, self.category, self.amount, self.importance, self.source, self.remarks,
                    self.key]
        return [self.date, self.item, self.amount, self.source, self.remarks, self.key]


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
        yield key, t, rule, answer, who_of(t, config.people)


def who_of(t: Transaction, people: dict[str, str]) -> str:
    """"To Jane Tan" / "From Jane Tan", or the shop: for the To Update card."""
    if t.counterparty:
        person = short_name(t.counterparty, people)
        return f"From {person}" if t.amount > 0 else f"To {person}"
    return t.description


def build_rows(
    transactions: list[Transaction], config: Config, answers: dict[str, dict] | None = None
) -> list[AccountRow]:
    """Rows for the accounts: everything that isn't excluded (rules 1-2).
    Rows the statement doesn't explain go in with what it does say, e.g.
    Item "Transfer", Category blank, Remarks the statement's text."""
    rows = []
    for key, t, rule, answer, who in _classify(transactions, config, answers or {}):
        category = answer.get("category") or rule.get("category", "") or t.category
        importance = answer.get("importance") or rule.get("importance", "")
        item = answer.get("item") or rule.get("item") or _sentence(t.purpose) or _fallback_item(t)
        kind = "earn" if t.amount > 0 else "spend"
        category = category if category in config.categories else ""
        needs: list[str] = []
        if not answer.get("reviewed") and key not in config.reviewed:  # you've seen its card: don't ask again
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
                remarks=answer.get("remarks") or rule.get("remarks") or t.description,
                key=key,
                who=who,
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
                    r.date, r.amount if r.kind == "earn" else -r.amount, r.who, r.statement,
                    r.item, ", ".join(labels[n] for n in r.needs), tab.title, r.key,
                ])
    if len(table) == 1:
        table.append(["Nothing to update."] + [""] * (len(TO_UPDATE_HEADERS) - 1))
    return table


def _fallback_item(t: Transaction) -> str:
    """Item when the statement gives no purpose: the shop name for a card
    charge, or how the money moved for a person ("Transfer", "QR payment");
    who it was is on the To Update card."""
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
    X5 and X6 depend on the other tabs; see month_links()."""
    cells: dict[str, object] = {"A1": "Spendings", f"{EARN_COLS[0]}1": "Earnings"}
    for col, h in zip(SPEND_COLS, SPEND_HEADERS):
        cells[f"{col}2"] = h
    for col, h in zip(EARN_COLS, EARN_HEADERS):
        cells[f"{col}2"] = h
    cells[f"{SPEND_KEY}2"] = "Key"
    cells[f"{EARN_KEY}2"] = "Key"
    amounts = _rng("D", FIRST_ROW, open_ended)

    def block(cols: str, data_col: str, heading: str, labels: list[str]) -> None:
        label_col, value_col = cols
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

    block(CAT_COLS, "C", "Category", config.categories)
    block(IMP_COLS, "E", "Importance", config.importance)

    label = SUMMARY_COLS[0]
    cells[f"{label}2"] = "Summary"
    cells[f"{SUMMARY_COLS[1]}2"] = "RM"
    cells[f"{label}3"] = "Earnings"
    cells[EARNINGS_CELL] = f"=SUM({_rng(EARN_COLS[2], FIRST_ROW, open_ended)})"
    cells[f"{label}4"] = "Spendings"
    cells[SPENDINGS_CELL] = f"=SUM({amounts})"
    cells[f"{label}5"] = "Trips"
    cells[f"{label}6"] = "Final"
    return cells


def col_letter(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def col_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def currency_cols(i: int) -> list[str]:
    """Date, Item, Category, Amount, Importance, Remarks of the trip's i-th currency block."""
    start = CURRENCY_START + i * (len(CASH_HEADERS) + 1)
    return [col_letter(start + k) for k in range(len(CASH_HEADERS))]


def received_cols(n_currencies: int) -> list[str]:
    """Date, Item, Currency, Amount, Remarks of money received in other currencies."""
    start = CURRENCY_START + n_currencies * (len(CASH_HEADERS) + 1)
    return [col_letter(start + k) for k in range(len(RECEIVED_HEADERS))]


def trip_width(trip: Trip) -> int:
    n = len(trip.currencies())
    return CURRENCY_START + n * (len(CASH_HEADERS) + 1) + (len(RECEIVED_HEADERS) + 1 if n else 0)


def trip_layout(trip: Trip, config: Config, open_ended: bool) -> dict[str, object]:
    """Headings and summary of a trip tab, laid out like the 2025 trip sheets:
    RM spending, what friends paid you back, then a spending block per
    currency. The trip total (Q4) is what you really paid:
    RM spent + each currency's spending x its rate - paid back."""
    r = TRIP_FIRST_ROW
    cells: dict[str, object] = {"A1": trip.name}
    if trip.link:
        cells["C1"] = f'=HYPERLINK("{trip.link}","Trip Link")'
    cells["A2"] = "Spending (RM)"
    for col, h in zip(SPEND_COLS, SPEND_HEADERS):
        cells[f"{col}3"] = h
    cells[f"{SPEND_KEY}3"] = "Key"
    cells[f"{PAID_COLS[0]}2"] = "Paid back to you (RM)"
    for col, h in zip(PAID_COLS, PAID_HEADERS):
        cells[f"{col}3"] = h
    cells[f"{PAID_KEY}3"] = "Key"

    L, V = TRIP_SUMMARY_COLS
    rm = _rng("D", r, open_ended)
    items = _rng("B", r, open_ended)
    cells[f"{L}3"] = "Summary"
    cells[f"{V}3"] = "RM"
    cells[f"{L}4"] = "Trip Total (RM)"
    cells[f"{L}5"] = "Spent in RM"
    cells[f"{V}5"] = f'=SUM({rm})-SUMIF({items},"{MONEY_EXCHANGE}",{rm})'
    cells[f"{L}6"] = "Paid back to you"
    cells[f"{V}6"] = f"=SUM({_rng(PAID_COLS[2], r, open_ended)})"

    in_rm = []
    for i, (cur, rate) in enumerate(trip.currencies()):
        c = currency_cols(i)
        cells[f"{c[0]}2"] = f"Spending in {cur}"
        for col, h in zip(c, CASH_HEADERS):
            cells[f"{col}3"] = f"Amount ({cur})" if h == "Amount" else h
        row = 8 + 4 * i
        cells[f"{L}{row}"] = f"Spent in {cur}"
        cells[f"{V}{row}"] = f"=SUM({_rng(c[3], r, open_ended)})"
        cells[f"{L}{row + 1}"] = f"RM per 1 {cur}"
        cells[f"{V}{row + 1}"] = rate if rate else ""
        cells[f"{L}{row + 2}"] = f"{cur} spending in RM"
        cells[f"{V}{row + 2}"] = f"={V}{row}*{V}{row + 1}"
        in_rm.append(f"{V}{row + 2}")
    if trip.currencies():
        rc = received_cols(len(trip.currencies()))
        cells[f"{rc[0]}2"] = "Received in other currencies (money exchange, leftovers)"
        for col, h in zip(rc, RECEIVED_HEADERS):
            cells[f"{col}3"] = h
    cells[TRIP_TOTAL_CELL] = f"={V}5-{V}6" + "".join(f"+{x}" for x in in_rm)
    return cells


def rate_cells(trip: Trip) -> list[str]:
    """Where each currency's rate sits in the summary (to read or write it)."""
    V = TRIP_SUMMARY_COLS[1]
    return [f"{V}{9 + 4 * i}" for i in range(len(trip.currencies()))]


def month_links(month_titles: list[str], trips: list[Trip], trip_titles: set[str]) -> dict[str, dict[str, str]]:
    """X5 (trips paid this month) and X6 (Final) for every month tab. Written
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
        out[title] = {
            TRIPS_CELL: trips_formula,
            FINAL_CELL: f"={carried}{EARNINGS_CELL}-{SPENDINGS_CELL}-{TRIPS_CELL}",
        }
    return out


def year_summary_cells(month_titles: list[str], trip_titles: list[str], extra_earnings: list[str] = (),
                       extra_spending: list[str] = ()) -> dict[str, object]:
    """extra_*: cells to add (custom sheets' RM totals, e.g. ang pao)."""
    if not month_titles and not extra_earnings and not extra_spending:
        return {}
    months = sorted(month_titles, key=parse_month_title)
    earnings = "+".join([f"{quote(t)}!{EARNINGS_CELL}" for t in months] + list(extra_earnings)) or "0"
    spending = "+".join([f"{quote(t)}!{SPENDINGS_CELL}" for t in months] + list(extra_spending)) or "0"
    trips = "+".join(f"{quote(t)}!{TRIP_TOTAL_CELL}" for t in trip_titles) or "0"
    return {
        "A1": "Total Earnings", "B1": f"={earnings}",
        "A2": "Total Spending", "B2": f"={spending}+B4",
        "A3": "Difference", "B3": "=B1-B2",
        "A4": "of which Trips", "B4": f"={trips}",
    }

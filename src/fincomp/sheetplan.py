"""What to read from and write to a yearly "YYYY Accounts" spreadsheet, as
plain data: no HTTP, no gspread. The CLI executes these plans with gspread
(gsheets.py); the web app executes the same plans with fetch() against the
Sheets API, so both write exactly the same thing.

A sync is two steps:

1. `prepare(year, existing tab titles, tabs, config)` says which tabs to
   add (in order, with their positions), which placeholder to delete, and
   which ranges to read.
2. After those tabs exist and the ranges are read, `finish(...)` returns
   the `values:batchUpdate` data, the `batchUpdate` requests and the ranges
   to clear.

Rules it keeps: only new rows are appended (hidden keys in G/R tell old
from new); existing rows are only touched for the user's own answers (just
the answered cells) or removed when the user said "not mine"; tabs fincomp
doesn't manage are never moved or written.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .accounts import (
    CAT_COLS, COLOURS, EARN_COLS, EARN_KEY, FINAL_CELL, FIRST_ROW, IMP_COLS, PAID_COLS, PAID_KEY, SPEND_COLS,
    SPEND_KEY, SUMMARY_COLS, TO_UPDATE, TO_UPDATE_HEADERS, TRIP_FIRST_ROW, TRIP_SUMMARY_COLS, TRIPS_CELL, YEAR_SUMMARY,
    AccountRow, Tab, col_letter, col_number, currency_cols, month_layout, month_links, parse_month_title, quote,
    received_cols, tab_order, to_update_table, trip_layout, trip_width, year_summary_cells,
)
from .config import Config

TAB_ROWS = 1000
TAB_COLS = 26
SPEND_FIELDS = {"date": "A", "item": "B", "category": "C", "amount": "D", "importance": "E", "source": "F",
                "remarks": "G"}
EARN_FIELDS = {"date": "P", "item": "Q", "amount": "R", "source": "S", "remarks": "T"}
GAP_COLS = {"month": "ILOV"}  # blank columns between sections (trips: trip_gaps)
CLEARABLE = {"remarks", "source"}  # fields an edit may empty


@dataclass
class TabToAdd:
    title: str
    index: int
    rows: int
    cols: int


@dataclass
class Prepared:
    add: list[TabToAdd]  # create these, in this order, at these positions
    delete: list[str]  # then delete these (the empty first tab of a new spreadsheet)
    order: list[str]  # tab titles after that
    new_tabs: set[str]  # tabs that need their layout written
    reads: list[str]  # ranges to read with valueRenderOption=FORMULA
    widths: dict[str, int] = field(default_factory=dict)  # columns each trip tab needs (one block per currency)


@dataclass
class Finished:
    data: list[dict]  # for values:batchUpdate (valueInputOption USER_ENTERED)
    requests: list[dict]  # for spreadsheets:batchUpdate, after the data
    clear: list[str]  # ranges to clear, before the data
    added: int = 0
    already: int = 0
    to_update: int = 0  # cards still open
    fixed_in_sheet: int = 0  # cards closed because the user edited the month tab
    synced_keys: set[str] = field(default_factory=set)  # answers now in the sheet


# ---- helpers ----------------------------------------------------------------


# Text that USER_ENTERED would turn into a date or number: "August 2026"
# (a tab name), "3/8", "12345", "1,200.50", "10%".
LOOKS_LIKE_VALUE = re.compile(r"[A-Za-z]{3,9}\.? \d{4}|\d{1,4}[/.-]\d{1,2}([/.-]\d{1,4})?|[\d,]+(\.\d+)?%?")


def text_value(v):
    # USER_ENTERED would turn "+6012..." or "=..." into numbers/formulas,
    # and "August 2026" into a date.
    if isinstance(v, str) and (v[:1] in ("=", "+", "-", "@") or LOOKS_LIKE_VALUE.fullmatch(v.strip())):
        return "'" + v
    return v


def cell(v):
    return v.isoformat() if hasattr(v, "isoformat") else text_value(v)


def col_index(letter: str) -> int:
    return col_number(letter)


def trip_gaps(trip) -> list[str]:
    """Blank columns of a trip tab: after RM spending, paid back, summary, and each currency block."""
    gaps = ["I", "O", "R"]
    n = len(trip.currencies()) if trip else 0
    for i in range(n):
        gaps.append(col_letter(col_index(currency_cols(i)[-1]) + 1))
    return gaps


def grid(sheet_id: int, r0: int, r1: int | None, c0: int, c1: int) -> dict:
    g = {"sheetId": sheet_id, "startRowIndex": r0, "startColumnIndex": c0, "endColumnIndex": c1}
    if r1 is not None:
        g["endRowIndex"] = r1
    return g


def insert_index(titles: list[str], order: tuple, config: Config) -> int:
    """Position for a new tab: just before the first managed tab that sorts
    after it, so tabs you made yourself (like "Chinese New Year" after
    January) stay next to the month they belong to."""
    for i, t in enumerate(titles):
        o = tab_order(t, config.trips)
        if (o is not None and o > order) or t == YEAR_SUMMARY:
            return i
    return len(titles)


def month_and_trip_tabs(order: list[str], year: int, config: Config) -> tuple[list[str], list[str]]:
    trip_names = {t.name for t in config.trips}
    months = [t for t in order if (ym := parse_month_title(t)) and ym[0] == year]
    trips = [t for t in order if t in trip_names]
    return months, trips


def data_ranges(months: list[str], trips: list[str]) -> list[str]:
    ranges = []
    for t in months:
        ranges += [f"{quote(t)}!A3:H", f"{quote(t)}!P3:U"]
    for t in trips:
        ranges.append(f"{quote(t)}!A4:H")
    return ranges


def locate(values: dict[str, list[list]]) -> dict[str, tuple[str, str, int, list]]:
    """key -> (quoted tab, "spend"/"earn", row number, row values)."""
    located = {}
    for rng, rows in values.items():
        tab_q = rng.rsplit("!", 1)[0]
        kind, key_index = ("earn", 5) if rng.endswith("!P3:U") else ("spend", 7)
        first = 4 if rng.endswith("!A4:H") else 3
        for i, r in enumerate(rows):
            if len(r) > key_index and r[key_index]:
                located[str(r[key_index])] = (tab_q, kind, first + i, r)
    return located


# ---- step 1 ---------------------------------------------------------------------


def prepare(year: int, titles: list[str], tabs: list[Tab], config: Config, created: bool = False) -> Prepared:
    order = list(titles)
    # A new spreadsheet comes with one empty tab ("Sheet1", or localised).
    placeholder = [order[0]] if created and order else []
    add, new_tabs = [], set()
    for tab in tabs:
        if tab.title not in order:
            i = insert_index(order, tab.order, config)
            cols = trip_cols(tab.trip) if tab.kind == "trip" and tab.trip else TAB_COLS
            add.append(TabToAdd(tab.title, i, TAB_ROWS, cols))
            order.insert(i, tab.title)
            new_tabs.add(tab.title)
    if YEAR_SUMMARY not in order:
        add.append(TabToAdd(YEAR_SUMMARY, len(order), 20, 4))
        order.append(YEAR_SUMMARY)
    if TO_UPDATE not in order:
        add.append(TabToAdd(TO_UPDATE, 0, TAB_ROWS, len(TO_UPDATE_HEADERS)))
        order.insert(0, TO_UPDATE)
        new_tabs.add(TO_UPDATE)
    for p in placeholder:
        order.remove(p)
    months, trips = month_and_trip_tabs(order, year, config)
    widths = {t.name: trip_cols(t) for t in config.trips if t.name in order}
    return Prepared(add, placeholder, order, new_tabs, data_ranges(months, trips), widths)


def trip_cols(trip) -> int:
    """Columns a trip tab needs: more than a new tab's 26 once it has a
    currency block or two (each 6 wide, then the received block)."""
    return max(TAB_COLS, trip_width(trip) + 2)


# ---- step 2 ---------------------------------------------------------------------


def finish(
    year: int,
    prepared: Prepared,
    sheet_ids: dict[str, int],
    values: dict[str, list[list]],
    tabs: list[Tab],
    config: Config,
    answers: dict[str, dict] | None = None,
    to_update: bool = True,
) -> Finished:
    """`to_update=False` when `tabs` are only a few rows placed by hand (add a
    transaction, move one to a trip): the To Update tab is left as it is."""
    answers = answers or {}
    months, trips = month_and_trip_tabs(prepared.order, year, config)
    filled = {rng: values.get(rng, []) for rng in prepared.reads}
    located = locate(filled)
    keys = set(located)
    ids = {quote(t): i for t, i in sheet_ids.items()}

    data: list[dict] = []
    formats: list[dict] = []
    removals: list[tuple[int, int, int, int]] = []
    sorts: list[dict] = []
    deleted: dict[tuple[str, str], int] = {}

    # Answers for rows already in the sheet: only the cells answered; rows
    # the user said aren't theirs are removed.
    for key, answer in answers.items():
        if key.startswith("_") or answer.get("synced") or key not in located:
            continue
        tab_q, kind, row, _ = located[key]
        if answer.get("skip"):
            removals.append(remove_row_range(ids[tab_q], kind, row))
            deleted[(tab_q, kind)] = deleted.get((tab_q, kind), 0) + 1
            continue
        data += set_cells(tab_q, kind, row, answer)

    added = already = 0
    for tab in tabs:
        q = quote(tab.title)
        sheet_id = sheet_ids[tab.title]
        if tab.title in prepared.new_tabs:
            layout = month_layout(config, True) if tab.kind == "month" else trip_layout(tab.trip, config, True)
            data += [{"range": f"{q}!{c}", "values": [[v]]} for c, v in layout.items()]
            formats += format_requests(sheet_id, tab, config)

        fresh = [r for r in tab.rows if r.key not in keys]
        already += len(tab.rows) - len(fresh)
        added += len(fresh)

        # Append new rows under what's there, then sort by date.
        blocks = [("spend", "A", "H", f"{q}!A{tab.first_row}:H" if tab.kind == "trip" else f"{q}!A3:H")]
        if tab.kind == "month":
            blocks.append(("earn", "P", "U", f"{q}!P3:U"))
        for kind, c0, c1, rng in blocks:
            block = [r for r in fresh if r.kind == kind]
            if not block:
                continue
            existing = len(filled.get(rng, []))
            start = tab.first_row + existing
            data.append({
                "range": f"{q}!{c0}{start}:{c1}{start + len(block) - 1}",
                "values": [[cell(v) for v in r.values()] for r in block],
            })
            remaining = existing - deleted.get((q, kind), 0) + len(block)
            sorts.append(sort_request(sheet_id, tab.first_row, col_index(c0), col_index(c1) + 1, remaining))

    # Tabs and trips may have been added since last time: re-link every
    # month's Trips and Final, and the year summary.
    for t, cells in month_links(months, config.trips, set(trips)).items():
        for c in (TRIPS_CELL, FINAL_CELL):
            data.append({"range": f"{quote(t)}!{c}", "values": [[cells[c]]]})
    from .custom import summary_refs

    extra = summary_refs(config.sheets, set(prepared.order), year)
    for c, value in year_summary_cells(months, trips, *extra).items():
        data.append({"range": f"{quote(YEAR_SUMMARY)}!{c}", "values": [[value]]})

    # The To Update tab: what's still missing, minus rows the user fixed
    # by editing the month tab.
    resolved = {r.key for tab in tabs for r in tab.rows if r.needs and fixed_in_sheet(r, located.get(r.key))}
    table = to_update_table(tabs, resolved)
    if TO_UPDATE in prepared.new_tabs:
        formats += to_update_formats(sheet_ids[TO_UPDATE])
    clear = []
    if to_update or TO_UPDATE in prepared.new_tabs:
        data.append({
            "range": f"{quote(TO_UPDATE)}!A1:H{len(table)}",
            "values": [[cell(v) for v in row] for row in table],
        })
        clear = [f"{quote(TO_UPDATE)}!A{len(table) + 1}:H{TAB_ROWS}"]

    # Removals bottom-up so the other row numbers stay right, then sorts.
    requests = formats + [
        {"deleteRange": {"range": grid(sid, row - 1, row, c0, c1), "shiftDimension": "ROWS"}}
        for sid, row, c0, c1 in sorted(removals, key=lambda d: -d[1])
    ] + sorts

    in_sheet = keys | {r.key for tab in tabs for r in tab.rows}
    synced = {k for k in answers if not k.startswith("_") and k in in_sheet}
    open_cards = 0 if table[1][0] == "Nothing to update." else len(table) - 1
    return Finished(data, requests, clear, added, already, open_cards, len(resolved), synced)


# ---- single-row edits (cards and row edits from the app) ------------------------


def set_cells(tab_q: str, kind: str, row: int, fields: dict) -> list[dict]:
    """values:batchUpdate entries writing only the given fields of one row
    (a field given as "" clears that cell)."""
    cols = SPEND_FIELDS if kind == "spend" else EARN_FIELDS
    fields = dict(fields)
    if isinstance(fields.get("date"), str) and fields["date"]:
        fields["date"] = date.fromisoformat(fields["date"][:10])  # a real date, not text
    return [
        {"range": f"{tab_q}!{col}{row}", "values": [[cell(fields[name])]]}
        for name, col in cols.items()
        if fields.get(name) is not None and (fields[name] != "" or name in CLEARABLE)
    ]


def remove_row_range(sheet_id: int, kind: str, row: int) -> tuple[int, int, int, int]:
    """Only the row's own block (Spendings A-H or Earnings P-U): the other
    block shares the sheet row."""
    c0, c1 = ("A", "H") if kind == "spend" else ("P", "U")
    return sheet_id, row, col_index(c0), col_index(c1) + 1


def remove_row_request(sheet_id: int, kind: str, row: int) -> dict:
    sid, r, c0, c1 = remove_row_range(sheet_id, kind, row)
    return {"deleteRange": {"range": grid(sid, r - 1, r, c0, c1), "shiftDimension": "ROWS"}}


def fixed_in_sheet(row: AccountRow, found: tuple | None) -> bool:
    """The user edited the month tab: the Item is no longer the placeholder,
    and/or a Category is filled in."""
    if not found:
        return False
    _, kind, _, values = found
    item = str(values[1]) if len(values) > 1 else ""
    category = str(values[2]) if kind == "spend" and len(values) > 2 else ""
    ok = True
    if "purpose" in row.needs:
        ok = ok and bool(item) and item != row.item
    if "category" in row.needs:
        ok = ok and bool(category)
    return ok


# ---- formatting -----------------------------------------------------------------


def sort_request(sheet_id: int, first_row: int, c0: int, c1: int, n_rows: int) -> dict:
    return {
        "sortRange": {
            "range": grid(sheet_id, first_row - 1, first_row - 1 + n_rows, c0, c1),
            "sortSpecs": [{"dimensionIndex": c0, "sortOrder": "ASCENDING"}],
        }
    }


def format_requests(sheet_id: int, tab: Tab, config: Config) -> list[dict]:
    first = tab.first_row - 1  # 0-based

    def number(col: str, pattern: str, kind: str = "NUMBER", r0: int = first, r1: int | None = None) -> dict:
        c = col_index(col)
        return {
            "repeatCell": {
                "range": grid(sheet_id, r0, r1, c, c + 1),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }

    def dropdown(col: str, values: list[str]) -> dict:
        return dropdown_request(sheet_id, first, col, values)

    def column(col: str, **props) -> dict:
        c = col_index(col)
        return {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                "properties": props,
                "fields": ",".join(props),
            }
        }

    def fill(r0: int, r1: int, c0: str, c1: str, colour: str) -> dict:
        return {
            "repeatCell": {
                "range": grid(sheet_id, r0, r1, col_index(c0), col_index(c1) + 1),
                "cell": {"userEnteredFormat": {"backgroundColor": COLOURS[colour]}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        }

    def bold(r0: int, r1: int) -> dict:
        return {
            "repeatCell": {
                "range": grid(sheet_id, r0, r1, 0, TAB_COLS),
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        }

    def freeze(rows: int) -> dict:
        return {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": rows}},
                "fields": "gridProperties.frozenRowCount",
            }
        }

    gaps = [column(c, pixelSize=24, hiddenByUser=False)
            for c in (GAP_COLS["month"] if tab.kind == "month" else trip_gaps(tab.trip))]
    if tab.kind == "month":
        s0, s1, e0, e1 = SPEND_COLS[0], SPEND_COLS[-1], EARN_COLS[0], EARN_COLS[-1]
        return [
            number("A", "dd/mm/yyyy", "DATE"), number(e0, "dd/mm/yyyy", "DATE"),
            *(number(c, "#,##0.00") for c in ("D", EARN_COLS[2], CAT_COLS[1], IMP_COLS[1], SUMMARY_COLS[1])),
            dropdown("C", config.categories), dropdown("E", config.importance), clear_validation(sheet_id, "F"),
            column("B", pixelSize=240), column(EARN_COLS[1], pixelSize=220),
            column("F", pixelSize=110, hiddenByUser=False), column(EARN_COLS[3], pixelSize=110, hiddenByUser=False),
            column("G", pixelSize=260, hiddenByUser=False), column(EARN_COLS[4], pixelSize=260),
            column(SPEND_KEY, hiddenByUser=True), column(EARN_KEY, hiddenByUser=True), *gaps,
            fill(0, 2, s0, s1, "spend"), fill(0, 2, e0, e1, "earn"),
            fill(1, 2, CAT_COLS[0], CAT_COLS[1], "summary"), fill(1, 2, IMP_COLS[0], IMP_COLS[1], "summary"),
            fill(1, 2, SUMMARY_COLS[0], SUMMARY_COLS[1], "summary"), fill(5, 6, SUMMARY_COLS[0], SUMMARY_COLS[1], "final"),
            bold(0, 2), freeze(2),
        ]

    L, V = TRIP_SUMMARY_COLS
    p = PAID_COLS
    reqs = [
        number("A", "dd/mm/yyyy", "DATE"), number("D", "#,##0.00"), number(V, "#,##0.00", r0=3),
        number(p[0], "dd/mm/yyyy", "DATE"), number(p[2], "#,##0.00"),
        dropdown("C", config.categories), dropdown("E", config.importance), clear_validation(sheet_id, "F", first),
        column("B", pixelSize=220), column("F", pixelSize=110, hiddenByUser=False),
        column("G", pixelSize=220, hiddenByUser=False), column(SPEND_KEY, hiddenByUser=True),
        column(p[1], pixelSize=160), column(PAID_KEY, hiddenByUser=True), column(L, pixelSize=200), *gaps,
        fill(1, 3, SPEND_COLS[0], SPEND_COLS[-1], "spend"), fill(1, 3, p[0], p[-1], "earn"),
        fill(2, 3, L, V, "summary"), fill(3, 4, L, V, "final"),
        bold(0, 3), freeze(3),
    ]
    trip = tab.trip
    for i, _ in enumerate(trip.currencies() if trip else []):
        c = currency_cols(i)
        reqs += [
            number(c[0], "dd/mm/yyyy", "DATE"), number(c[3], "#,##0.00"),
            number(V, "0.000000", r0=8 + 4 * i, r1=9 + 4 * i),  # its rate
            dropdown(c[2], config.categories), dropdown(c[4], config.importance),
            column(c[1], pixelSize=200), fill(1, 3, c[0], c[-1], "cash"),
        ]
    if trip and trip.currencies():
        rc = received_cols(len(trip.currencies()))
        reqs += [number(rc[0], "dd/mm/yyyy", "DATE"), number(rc[3], "#,##0.00"), column(rc[1], pixelSize=200),
                 fill(1, 3, rc[0], rc[-1], "summary")]
    return reqs


def dropdown_request(sheet_id: int, first: int, col: str, values: list[str]) -> dict:
    c = col_index(col)
    return {
        "setDataValidation": {
            "range": grid(sheet_id, first, TAB_ROWS, c, c + 1),
            "rule": {
                "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in values]},
                "showCustomUi": True,
                "strict": False,
            },
        }
    }


def clear_validation(sheet_id: int, col: str, first: int = FIRST_ROW - 1) -> dict:
    """A column inserted next to a dropdown can inherit it: Source has none."""
    c = col_index(col)
    return {"setDataValidation": {"range": grid(sheet_id, first, TAB_ROWS, c, c + 1)}}


def to_update_formats(sheet_id: int) -> list[dict]:
    widths = [(2, 180), (3, 380), (4, 180), (5, 170)]
    return [
        {
            "repeatCell": {
                "range": grid(sheet_id, 0, 1, 0, len(TO_UPDATE_HEADERS)),
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
        {
            "repeatCell": {
                "range": grid(sheet_id, 1, None, 0, 1),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        *(
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                    "properties": {"pixelSize": px},
                    "fields": "pixelSize",
                }
            }
            for c, px in widths
        ),
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 7, "endIndex": 8},
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        },
    ]


# ---- reading for the app (valueRenderOption UNFORMATTED_VALUE) ------------------

SHEETS_EPOCH = date(1899, 12, 30)  # day 0 of Sheets' date serial numbers


def as_date(v) -> date | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return SHEETS_EPOCH + timedelta(days=int(v))
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def as_amount(v) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def summary_ranges(month_title: str) -> list[str]:
    """The month's own summary cells: what its formulas computed."""
    q = quote(month_title)
    c, i, s = CAT_COLS, IMP_COLS, SUMMARY_COLS
    return [f"{q}!{c[0]}3:{c[1]}40", f"{q}!{i[0]}3:{i[1]}20", f"{q}!{s[0]}3:{s[1]}6"]


def parse_summary(by_category: list[list], by_importance: list[list], totals: list[list]) -> dict:
    def pairs(rows):
        out = {}
        for r in rows:
            if len(r) >= 2 and str(r[0]).strip():
                out[str(r[0])] = as_amount(r[1])
        return out

    t = pairs(totals)
    return {
        "byCategory": pairs(by_category),
        "byImportance": pairs(by_importance),
        "earnings": t.get("Earnings", 0.0),
        "spendings": t.get("Spendings", 0.0),
        "trips": t.get("Trips", 0.0),
        "final": t.get("Final", 0.0),
    }


def rows_from_values(spend: list[list], earn: list[list], first_row: int = 3) -> list[dict]:
    """The month tab's rows for the app's list and edit screen. Rows without
    a key were typed by hand: shown, but read-only in the app."""
    out = []
    for i, r in enumerate(spend):
        if not any(str(c).strip() for c in r[:7]):
            continue
        out.append({
            "kind": "spend", "row": first_row + i, "date": (d := as_date(r[0] if r else "")) and d.isoformat(),
            "item": _get(r, 1), "category": _get(r, 2), "amount": as_amount(_get(r, 3)),
            "importance": _get(r, 4), "source": _get(r, 5), "remarks": _get(r, 6), "key": _get(r, 7),
        })
    for i, r in enumerate(earn):
        if not any(str(c).strip() for c in r[:5]):
            continue
        out.append({
            "kind": "earn", "row": first_row + i, "date": (d := as_date(r[0] if r else "")) and d.isoformat(),
            "item": _get(r, 1), "category": "", "amount": as_amount(_get(r, 2)),
            "importance": "", "source": _get(r, 3), "remarks": _get(r, 4), "key": _get(r, 5),
        })
    return out


def cards_from_values(rows: list[list]) -> list[dict]:
    """The To Update tab (A2:H) as cards, with the tab row each came from."""
    cards = []
    for i, r in enumerate(rows):
        if not r or str(r[0]).startswith("Nothing to update"):
            continue
        needs = [n.strip() for n in _get(r, 5).split(",") if n.strip()]
        cards.append({
            "row": 2 + i, "date": (d := as_date(r[0])) and d.isoformat(), "amount": as_amount(_get(r, 1)),
            "who": _get(r, 2), "statement": _get(r, 3), "recordedAs": _get(r, 4),
            "needsPurpose": "what it was for" in needs, "needsCategory": "Category" in needs,
            "tab": _tab_title(r[6] if len(r) > 6 else ""), "key": _get(r, 7),
        })
    return cards


def _tab_title(v) -> str:
    """The Tab column. Sheets may have turned "August 2026" into a date
    (written before tab names were kept as text): turn it back."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and (d := as_date(v)):
        return f"{calendar.month_name[d.month]} {d.year}"
    return str(v or "")


def _get(r: list, i: int) -> str:
    return "" if i >= len(r) or r[i] is None else str(r[i])


def edit_plan(key: str, values: dict[str, list[list]], sheet_ids: dict[str, int], fields: dict,
              remove: bool = False) -> tuple[list[dict], list[dict]]:
    """Write `fields` (item/category/importance/remarks) into the row with
    `key`, or remove that row ("not mine"). `values` are the tab's data
    ranges as read (A3:H and P3:U, or A4:H for a trip). Returns
    (values:batchUpdate data, batchUpdate requests)."""
    found = locate(values).get(key)
    if not found:
        return [], []
    tab_q, kind, row, _ = found
    if remove:
        ids = {quote(t): i for t, i in sheet_ids.items()}
        return [], [remove_row_request(ids[tab_q], kind, row)]
    return set_cells(tab_q, kind, row, fields), []


def remove_card_request(to_update_sheet_id: int, row: int) -> dict:
    """Take an answered card off the To Update tab."""
    return {
        "deleteDimension": {
            "range": {"sheetId": to_update_sheet_id, "dimension": "ROWS", "startIndex": row - 1, "endIndex": row}
        }
    }


def category_refresh(sheet_ids: dict[str, int], year: int, config: Config) -> dict:
    """After the category list changes: rewrite every month tab's "By
    Category" block and the Category dropdowns (month C, trip C and the trip
    currency block's Category) so a new category is offered and summed
    everywhere. Nothing else is touched. Returns {"clear", "data", "requests"}."""
    months, trips = month_and_trip_tabs(list(sheet_ids), year, config)
    layout = month_layout(config, True)
    block = {c: v for c, v in layout.items() if c[0] in CAT_COLS}
    clear, data, requests = [], [], []
    for t in months:
        q = quote(t)
        clear.append(f"{q}!{CAT_COLS[0]}3:{CAT_COLS[1]}40")
        data += [{"range": f"{q}!{c}", "values": [[v]]} for c, v in block.items()]
        requests.append(dropdown_request(sheet_ids[t], FIRST_ROW - 1, "C", config.categories))
    for t in trips:
        requests.append(dropdown_request(sheet_ids[t], TRIP_FIRST_ROW - 1, "C", config.categories))
        trip = next(x for x in config.trips if x.name == t)
        for i, _ in enumerate(trip.currencies()):
            requests.append(dropdown_request(sheet_ids[t], TRIP_FIRST_ROW - 1, currency_cols(i)[2], config.categories))
    return {"clear": clear, "data": data, "requests": requests}


# ---- tabs made before the Source column and the gap columns (Oct 2026) ----------
#
# Columns are inserted, not rewritten, so every row, your edits, and formulas
# pointing at these tabs (Final, Trips, Year End Summary) move along with
# them. Then Source is filled in and the old automatic Remarks ("To Jane
# Tan", or the bank) become the statement text.

# 0-based columns of the old layout to insert one column before, right to left
# so earlier inserts don't shift later ones.
OLD_MONTH_INSERTS = [18, 16, 7, 5]  # before S (gap), Q (Source), H (gap), F (Source)


def header_ranges(year: int, titles: list[str], config: Config) -> list[str]:
    """Each managed tab's header row, to tell old layouts from new."""
    months, trips = month_and_trip_tabs(list(titles), year, config)
    return [f"{quote(t)}!A2:H2" for t in months] + [f"{quote(t)}!A3:Z3" for t in trips]


def trip_versions(headers: dict[str, list[list]]) -> dict[str, str]:
    """Trip tabs in an older layout: {title: "v1" (before Oct 2026) or "v2"
    (Source column, one currency)}. Current ones aren't listed."""
    out = {}
    for rng, rows in headers.items():
        if not rng.endswith("!A3:Z3"):
            continue
        row = [str(v).strip() for v in (rows[0] if rows else [])] + [""] * 26
        title = rng.rsplit("!", 1)[0][1:-1].replace("''", "'")
        if row[15] == "Summary":
            continue  # current layout
        if row[5] == "Remarks" and row[6] == "Key":
            out[title] = "v1"
        elif row[6] == "Remarks" and row[7] == "Key":
            out[title] = "v2"
    return out


def trip_rebuild(trip, version: str, rows: list[list], by_key: dict[str, AccountRow], config: Config,
                 sheet_id: int) -> tuple[list[str], list[dict], list[dict]]:
    """A trip tab in an older layout (rows A4 onwards, read with FORMULA)
    rewritten in the current one: RM rows keep their keys, the currency
    block goes to the first currency, money received to "received in other
    currencies". Returns (clear, data, requests)."""
    q = quote(trip.name)
    if version == "v1":
        rm_at, key_at, cash_at, received_at = 0, 6, 7, 16
    else:
        rm_at, key_at, cash_at, received_at = 0, 7, 9, 19
    rm, cash, received = [], [], []
    cur = trip.currency or ""
    for r in rows:
        r = list(r) + [""] * 30
        if any(str(v).strip() for v in r[rm_at:key_at + 1]):
            if version == "v1":
                d, item, cat, amt, imp, remarks, key = r[0:7]
                source = ""
                known = by_key.get(str(key))
                if known:
                    source = known.source
                    if str(remarks) in (known.who, known.source):
                        remarks = known.remarks
            else:
                d, item, cat, amt, imp, source, remarks, key = r[0:8]
            rm.append([d, item, cat, amt, imp, source, remarks, key])
        if any(str(v).strip() for v in r[cash_at:cash_at + 6]):
            cash.append(r[cash_at:cash_at + 6])
        if any(str(v).strip() for v in r[received_at:received_at + 4]):
            d, item, amt, remarks = r[received_at:received_at + 4]
            received.append([d, item, cur, amt, remarks])
    last = col_letter(max(trip_width(trip), 30) - 1)
    clear = [f"{q}!A1:{last}{TAB_ROWS}"]
    data = [{"range": f"{q}!{c}", "values": [[v]]} for c, v in trip_layout(trip, config, True).items()]
    first = TRIP_FIRST_ROW
    if rm:
        data.append({"range": f"{q}!A{first}:{SPEND_KEY}{first + len(rm) - 1}", "values": rm})
    if cash and trip.currencies():
        c = currency_cols(0)
        data.append({"range": f"{q}!{c[0]}{first}:{c[-1]}{first + len(cash) - 1}", "values": cash})
    if received and trip.currencies():
        rc = received_cols(len(trip.currencies()))
        data.append({"range": f"{q}!{rc[0]}{first}:{rc[-1]}{first + len(received) - 1}", "values": received})
    unhide = {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": col_index(last) + 1},
        "properties": {"hiddenByUser": False}, "fields": "hiddenByUser"}}
    widen = {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {
        "columnCount": max(trip_width(trip) + 2, 30)}}, "fields": "gridProperties.columnCount"}}
    return clear, data, [widen, unhide, *format_requests(sheet_id, Tab(trip.name, "trip", (), trip=trip), config)]


def old_tabs(headers: dict[str, list[list]]) -> list[str]:
    """Month tabs whose header still has Remarks in F and the key in G."""
    out = []
    for rng, rows in headers.items():
        if not rng.endswith("!A2:H2"):
            continue
        row = rows[0] if rows else []
        if len(row) >= 7 and str(row[5]) == "Remarks" and str(row[6]) == "Key":
            out.append(rng.rsplit("!", 1)[0][1:-1].replace("''", "'"))
    return out


def unfinished_tabs(headers: dict[str, list[list]]) -> list[str]:
    """Month tabs with columns inserted but headers not rewritten yet (an upgrade cut short)."""
    out = []
    for rng, rows in headers.items():
        if not rng.endswith("!A2:H2"):
            continue
        row = (rows[0] if rows else []) + [""] * 8
        if not str(row[5]).strip() and str(row[6]) == "Remarks" and str(row[7]) == "Key":
            out.append(rng.rsplit("!", 1)[0][1:-1].replace("''", "'"))
    return out


def insert_columns(sheet_ids: dict[str, int], titles: list[str]) -> list[dict]:
    reqs = []
    for t in titles:
        if not parse_month_title(t):
            continue  # trip tabs are rebuilt instead (trip_rebuild)
        for c in OLD_MONTH_INSERTS:
            reqs.append({
                "insertDimension": {
                    "range": {"sheetId": sheet_ids[t], "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                    "inheritFromBefore": False,
                }
            })
    return reqs


def upgrade_finish(sheet_ids: dict[str, int], titles: list[str], values: dict[str, list[list]], rows: list[AccountRow],
                   config: Config) -> tuple[list[str], list[dict], list[dict]]:
    """After insert_columns: the new headers, summaries and formats, plus
    Source and Remarks for rows fincomp recorded. `values` are the data
    ranges (data_ranges) read with FORMULA. Returns (ranges to clear first,
    data, requests)."""
    by_key = {r.key: r for r in rows}
    clear: list[str] = []
    data: list[dict] = []
    requests: list[dict] = []
    for t in titles:
        q = quote(t)
        if not parse_month_title(t):
            continue
        tab = Tab(t, "month", ())
        layout = month_layout(config, True)
        clear.append(f"{q}!{CAT_COLS[0]}3:{IMP_COLS[1]}40")  # old summaries, rewritten below
        data += [{"range": f"{q}!{c}", "values": [[v]]} for c, v in layout.items()]
        requests += format_requests(sheet_ids[t], tab, config)

    for key, (tab_q, kind, row, vals) in locate(values).items():
        if tab_q[1:-1].replace("''", "'") not in titles or key not in by_key:
            continue
        r = by_key[key]
        source_i, remarks_i = (5, 6) if kind == "spend" else (3, 4)
        fields = {}
        if not _get(vals, source_i):
            fields["source"] = r.source
        if _get(vals, remarks_i) in (r.who, r.source):  # what fincomp wrote before, never your own note
            fields["remarks"] = r.remarks
        data += set_cells(tab_q, kind, row, fields)
    return clear, data, requests


def links_plan(year: int, titles: list[str], config: Config) -> list[dict]:
    """Every month's Trips and Final, and the Year End Summary, written again
    (after a trip tab moved its total)."""
    from .custom import summary_refs

    months, trips = month_and_trip_tabs(list(titles), year, config)
    data = []
    for t, cells in month_links(months, config.trips, set(trips)).items():
        for c in (TRIPS_CELL, FINAL_CELL):
            data.append({"range": f"{quote(t)}!{c}", "values": [[cells[c]]]})
    if YEAR_SUMMARY in titles:
        extra = summary_refs(config.sheets, set(titles), year)
        for c, value in year_summary_cells(months, trips, *extra).items():
            data.append({"range": f"{quote(YEAR_SUMMARY)}!{c}", "values": [[value]]})
    return data


# ---- rows placed by hand: added in the app, or moved to/from a trip -------------


def take_row(key: str, values: dict[str, list[list]], sheet_ids: dict[str, int]) -> tuple[dict | None, list[dict]]:
    """The row with `key` as fields, and the request that removes it from
    its block (to put it somewhere else)."""
    found = locate(values).get(key)
    if not found:
        return None, []
    tab_q, kind, row, v = found
    if kind == "spend":
        fields = {"kind": "spend", "date": as_date(v[0] if v else ""), "item": _get(v, 1), "category": _get(v, 2),
                  "amount": as_amount(_get(v, 3)), "importance": _get(v, 4), "source": _get(v, 5),
                  "remarks": _get(v, 6), "key": key}
    else:
        fields = {"kind": "earn", "date": as_date(v[0] if v else ""), "item": _get(v, 1), "amount": as_amount(_get(v, 2)),
                  "source": _get(v, 3), "remarks": _get(v, 4), "key": key}
    ids = {quote(t): i for t, i in sheet_ids.items()}
    return fields, [remove_row_request(ids[tab_q], kind, row)]


def cash_row(values: list[list], tab_title: str, fields: dict, index: int = 0) -> list[dict]:
    """Spending in one of the trip's currencies (block `index`): written under its last row."""
    row = TRIP_FIRST_ROW + len(values)
    day = as_date(fields.get("date", ""))  # a real date, not the text "2026-11-03"
    vals = [day or "", fields.get("item", ""), fields.get("category", ""), fields.get("amount", ""),
            fields.get("importance", ""), fields.get("remarks", "")]
    c = currency_cols(index)
    return [{"range": f"{quote(tab_title)}!{c[0]}{row}:{c[-1]}{row}", "values": [[cell(v) for v in vals]]}]


def paid_row(values: list[list], tab_title: str, fields: dict) -> list[dict]:
    """Money paid back to you on a trip (RM), with a key so it can be found again."""
    row = TRIP_FIRST_ROW + len(values)
    day = as_date(fields.get("date", ""))
    vals = [day or "", fields.get("item", ""), round(float(fields.get("amount") or 0), 2), fields.get("remarks", ""),
            fields.get("key", "")]
    return [{"range": f"{quote(tab_title)}!{PAID_COLS[0]}{row}:{PAID_KEY}{row}", "values": [[cell(v) for v in vals]]}]


def trip_refresh(sheet_ids: dict[str, int], config: Config,
                 names: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """After trips change in Settings: each existing trip tab's headings,
    summary (currency, rate) and formats. Rows are never touched. `names`:
    only these trips (the ones you changed)."""
    data: list[dict] = []
    requests: list[dict] = []
    for trip in config.trips:
        if trip.name not in sheet_ids or (names is not None and trip.name not in names):
            continue
        q = quote(trip.name)
        data += [{"range": f"{q}!{c}", "values": [[v]]} for c, v in trip_layout(trip, config, True).items()]
        requests += format_requests(sheet_ids[trip.name], Tab(trip.name, "trip", (), trip=trip), config)
    return data, requests

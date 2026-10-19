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

from dataclasses import dataclass, field
from datetime import date, timedelta

from .accounts import (
    FINAL_CELL, TO_UPDATE, TO_UPDATE_HEADERS, TRIPS_CELL, YEAR_SUMMARY, AccountRow, Tab, month_layout,
    month_links, parse_month_title, quote, tab_order, to_update_table, trip_layout, year_summary_cells,
)
from .config import Config

TAB_ROWS = 1000
SPEND_FIELDS = {"item": "B", "category": "C", "importance": "E", "remarks": "F"}
EARN_FIELDS = {"item": "O", "remarks": "Q"}


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


def text_value(v):
    # USER_ENTERED would turn "+6012..." or "=..." into numbers/formulas.
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def cell(v):
    return v.isoformat() if hasattr(v, "isoformat") else text_value(v)


def col_index(letter: str) -> int:
    return ord(letter) - ord("A")


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
        ranges += [f"{quote(t)}!A3:G", f"{quote(t)}!N3:R"]
    for t in trips:
        ranges.append(f"{quote(t)}!A4:G")
    return ranges


def locate(values: dict[str, list[list]]) -> dict[str, tuple[str, str, int, list]]:
    """key -> (quoted tab, "spend"/"earn", row number, row values)."""
    located = {}
    for rng, rows in values.items():
        tab_q = rng.rsplit("!", 1)[0]
        kind, key_index = ("earn", 4) if rng.endswith("!N3:R") else ("spend", 6)
        first = 4 if rng.endswith("!A4:G") else 3
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
            add.append(TabToAdd(tab.title, i, TAB_ROWS, 20))
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
    return Prepared(add, placeholder, order, new_tabs, data_ranges(months, trips))


# ---- step 2 ---------------------------------------------------------------------


def finish(
    year: int,
    prepared: Prepared,
    sheet_ids: dict[str, int],
    values: dict[str, list[list]],
    tabs: list[Tab],
    config: Config,
    answers: dict[str, dict] | None = None,
) -> Finished:
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
        blocks = [("spend", "A", "G", f"{q}!A{tab.first_row}:G" if tab.kind == "trip" else f"{q}!A3:G")]
        if tab.kind == "month":
            blocks.append(("earn", "N", "R", f"{q}!N3:R"))
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
    for c, value in year_summary_cells(months, trips).items():
        data.append({"range": f"{quote(YEAR_SUMMARY)}!{c}", "values": [[value]]})

    # The To Update tab: what's still missing, minus rows the user fixed
    # by editing the month tab.
    resolved = {r.key for tab in tabs for r in tab.rows if r.needs and fixed_in_sheet(r, located.get(r.key))}
    table = to_update_table(tabs, resolved)
    if TO_UPDATE in prepared.new_tabs:
        formats += to_update_formats(sheet_ids[TO_UPDATE])
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
    """values:batchUpdate entries writing only the given fields of one row."""
    cols = SPEND_FIELDS if kind == "spend" else EARN_FIELDS
    return [
        {"range": f"{tab_q}!{col}{row}", "values": [[text_value(fields[name])]]}
        for name, col in cols.items()
        if fields.get(name)
    ]


def remove_row_range(sheet_id: int, kind: str, row: int) -> tuple[int, int, int, int]:
    """Only the row's own block (Spendings A-G or Earnings N-R): the other
    block shares the sheet row."""
    c0, c1 = ("A", "G") if kind == "spend" else ("N", "R")
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

    def number(col: str, pattern: str, kind: str = "NUMBER", r0: int = first) -> dict:
        c = col_index(col)
        return {
            "repeatCell": {
                "range": grid(sheet_id, r0, None, c, c + 1),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }

    def dropdown(col: str, values: list[str]) -> dict:
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

    def column(col: str, **props) -> dict:
        c = col_index(col)
        return {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c, "endIndex": c + 1},
                "properties": props,
                "fields": ",".join(props),
            }
        }

    def bold(r0: int, r1: int) -> dict:
        return {
            "repeatCell": {
                "range": grid(sheet_id, r0, r1, 0, 20),
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

    if tab.kind == "month":
        return [
            number("A", "dd/mm/yyyy", "DATE"), number("N", "dd/mm/yyyy", "DATE"),
            *(number(c, "#,##0.00") for c in "DPILT"),
            dropdown("C", config.categories), dropdown("E", config.importance),
            column("B", pixelSize=240), column("O", pixelSize=220),
            column("G", hiddenByUser=True), column("R", hiddenByUser=True),
            bold(0, 2), freeze(2),
        ]

    reqs = [
        number("A", "dd/mm/yyyy", "DATE"), number("D", "#,##0.00"),
        number("P", "#,##0.00", r0=3),
        dropdown("C", config.categories), dropdown("E", config.importance),
        column("B", pixelSize=220), column("O", pixelSize=170),
        column("G", hiddenByUser=True),
        bold(0, 3), freeze(3),
    ]
    if tab.trip and tab.trip.currency:
        reqs += [
            number("H", "dd/mm/yyyy", "DATE"), number("Q", "dd/mm/yyyy", "DATE"),
            number("K", "#,##0"), number("S", "#,##0"),
            {
                "repeatCell": {
                    "range": grid(sheet_id, 5, 6, col_index("P"), col_index("P") + 1),
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.00000"}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            },
            dropdown("J", config.categories), dropdown("L", config.importance),
            column("I", pixelSize=200), column("R", pixelSize=200),
        ]
    return reqs


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
    return [f"{q}!H3:I20", f"{q}!K3:L20", f"{q}!S3:T6"]


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
        if not any(str(c).strip() for c in r[:6]):
            continue
        out.append({
            "kind": "spend", "row": first_row + i, "date": (d := as_date(r[0] if r else "")) and d.isoformat(),
            "item": _get(r, 1), "category": _get(r, 2), "amount": as_amount(_get(r, 3)),
            "importance": _get(r, 4), "remarks": _get(r, 5), "key": _get(r, 6),
        })
    for i, r in enumerate(earn):
        if not any(str(c).strip() for c in r[:4]):
            continue
        out.append({
            "kind": "earn", "row": first_row + i, "date": (d := as_date(r[0] if r else "")) and d.isoformat(),
            "item": _get(r, 1), "category": "", "amount": as_amount(_get(r, 2)),
            "importance": "", "remarks": _get(r, 3), "key": _get(r, 4),
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
            "tab": _get(r, 6), "key": _get(r, 7),
        })
    return cards


def _get(r: list, i: int) -> str:
    return "" if i >= len(r) or r[i] is None else str(r[i])


def edit_plan(key: str, values: dict[str, list[list]], sheet_ids: dict[str, int], fields: dict,
              remove: bool = False) -> tuple[list[dict], list[dict]]:
    """Write `fields` (item/category/importance/remarks) into the row with
    `key`, or remove that row ("not mine"). `values` are the tab's data
    ranges as read (A3:G and N3:R, or A4:G for a trip). Returns
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

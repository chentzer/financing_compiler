"""What the website / Android app calls (through Pyodide). Everything in and
out is plain JSON-able data; the JavaScript side only does the HTTP calls
to Google between these steps.

Upload flow:
    1. JS reads the Settings sheet tabs, the Ledger tab and passwords.json.
    2. compile_upload(files, settings, passwords, ledger)  -> per-file results,
       the new Ledger rows to write, and the years touched.
    3. For each year: JS opens or creates "<year> Accounts", lists tab titles,
       prepare_year(year, titles, created) -> tabs to add/delete, ranges to read;
       JS does that, then finish_year(year, sheet_ids, values) -> data,
       requests, clear for JS to send.
The compiled result is kept here between those calls (one user, one page).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from . import settings as S
from . import overview, sheetplan
from .accounts import AccountRow, Tab, deduction_month, month_title, parse_month_title
from .pipeline import Compiled, compile_statements
from .suggest import suggest_categories

_state: dict = {}


def _config(settings: dict, passwords: dict | None):
    return S.config_from_tabs(settings or {}, passwords or {})


def compile_upload(files: list[dict], settings: dict, passwords: dict, ledger: list[list],
                   me: list[str] | None = None) -> dict:
    """files: [{"name": str, "data": bytes}]. settings: {tab: rows} of the
    Settings sheet. ledger: the Ledger tab's rows (header first). me: your
    name(s), for Splitwise exports."""
    config = _config(settings, passwords)
    config.me = [m for m in (me or []) if m]
    earlier = S.ledger_from_rows(ledger or [])
    compiled: Compiled = compile_statements([(f["name"], bytes(f["data"])) for f in files], config, earlier=earlier)
    _state.update(config=config, compiled=compiled, prepared={})
    names = {f["name"] for f in files}
    kept = [t for t in earlier if t.file not in names]
    return {
        "files": [asdict(f) | {"ok": f.ok} for f in compiled.files],
        "ledger": S.ledger_rows(kept + compiled.parsed),  # rewrite the Ledger tab with this (RAW)
        "years": sorted(compiled.tabs),
        "pairs": len(compiled.matches),
        "duplicates": compiled.duplicates,
        "toUpdate": sum(1 for r in compiled.rows if r.needs),
    }


def recompile(settings: dict, passwords: dict, ledger: list[list]) -> dict:
    """Same as an upload with no new files: re-applies rules to everything
    already uploaded (e.g. after editing Settings)."""
    return compile_upload([], settings, passwords, ledger)


def spreadsheet_title(year: int) -> str:
    return _state["config"].google.spreadsheet.replace("{year}", str(year))


def prepare_year(year: int, titles: list[str], created: bool = False) -> dict:
    tabs = _state["compiled"].tabs.get(year, [])
    prepared = sheetplan.prepare(year, list(titles), tabs, _state["config"], created)
    _state["prepared"][year] = prepared
    return {
        "add": [asdict(t) for t in prepared.add],
        "delete": prepared.delete,
        "reads": prepared.reads,
        "widths": prepared.widths,
    }


def finish_year(year: int, sheet_ids: dict, values: dict) -> dict:
    """sheet_ids: {tab title: sheetId} after the adds/deletes. values:
    {range: rows} read with valueRenderOption FORMULA."""
    tabs = _state["compiled"].tabs.get(year, [])
    done = sheetplan.finish(
        year, _state["prepared"][year], {k: int(v) for k, v in sheet_ids.items()}, values, tabs, _state["config"]
    )
    return {
        "clear": done.clear, "data": done.data, "requests": done.requests,
        "added": done.added, "already": done.already, "toUpdate": done.to_update,
    }


# ---- cards, rows, summary (reads use valueRenderOption UNFORMATTED_VALUE) -------

def cards(to_update_rows: list[list]) -> list[dict]:
    """To Update tab rows A2:H -> cards."""
    return sheetplan.cards_from_values(to_update_rows)


def tab_ranges(tab_title: str, trip: bool = False) -> list[str]:
    q = sheetplan.quote(tab_title)
    return [f"{q}!A4:H"] if trip else [f"{q}!A3:H", f"{q}!P3:U"]


def month_rows(spend: list[list], earn: list[list]) -> list[dict]:
    return sheetplan.rows_from_values(spend, earn)


def summary_ranges(month_title: str) -> list[str]:
    return sheetplan.summary_ranges(month_title)


def month_summary(by_category: list[list], by_importance: list[list], totals: list[list]) -> dict:
    return sheetplan.parse_summary(by_category, by_importance, totals)


def edit_row(key: str, values: dict, sheet_ids: dict, fields: dict) -> dict:
    """Card answer or row edit: only the given fields of that row."""
    data, requests = sheetplan.edit_plan(key, values, {k: int(v) for k, v in sheet_ids.items()}, fields)
    return {"data": data, "requests": requests}


def remove_row(key: str, values: dict, sheet_ids: dict, card: dict | None = None) -> dict:
    """"Not mine": remove the row, and the Removed-tab row to append (RAW)
    so it never comes back."""
    _, requests = sheetplan.edit_plan(key, values, {k: int(v) for k, v in sheet_ids.items()}, {}, remove=True)
    card = card or {}
    return {
        "requests": requests,
        "removed": S.removed_row(key, card.get("date") or "", card.get("amount") or 0, card.get("statement") or ""),
    }


def reviewed_row(key: str, card: dict | None = None) -> list:
    """"Skip": the Settings › Reviewed row to append, so the card never comes back."""
    card = card or {}
    return S.removed_row(key, card.get("date") or "", card.get("amount") or 0, card.get("statement") or "")


def remove_card(to_update_sheet_id: int, row: int) -> dict:
    return sheetplan.remove_card_request(int(to_update_sheet_id), int(row))


def rule_row(match: str, item: str = "", category: str = "", importance: str = "") -> list:
    """"Same for every … from now on": the Settings › Rules row to append."""
    rule = {"match": match}
    for k, v in (("item", item), ("category", category), ("importance", importance)):
        if v:
            rule[k] = v
    return S.rule_row(rule)


def categories(settings: dict) -> list[str]:
    """The category list (Settings › Lists, or the defaults)."""
    return _config(settings, {}).categories


def lists_rows(categories: list[str], settings: dict) -> list[list]:
    """Settings › Lists body (no header) with a new category list; the
    Importance column stays as it is."""
    config = _config(settings, {})
    config.categories = [c for c in dict.fromkeys(c.strip() for c in categories) if c]
    return S.tabs_from_config(config)[S.LISTS][1:]


def suggest(statement: str, who: str, item: str, history: list[list], cats: list[str]) -> list[str]:
    """Categories to offer first on a card. history: [item, remarks, category]."""
    return suggest_categories(statement, who, item, history, cats)


def category_refresh(year: int, sheet_ids: dict, settings: dict) -> dict:
    """After the category list changed: the month tabs' By Category blocks and dropdowns."""
    return sheetplan.category_refresh({k: int(v) for k, v in sheet_ids.items()}, int(year), _config(settings, {}))


def settings_template() -> dict:
    """Tabs for a brand-new Settings sheet (defaults), plus which to hide."""
    tabs = S.tabs_from_config(_config({}, {}))
    tabs[S.REMOVED] = [S.HEADERS[S.REMOVED]]
    tabs[S.REVIEWED] = [S.HEADERS[S.REVIEWED]]
    tabs[S.LEDGER] = [S.HEADERS[S.LEDGER]]
    return {"title": S.SETTINGS_TITLE, "tabs": tabs, "hidden": sorted(S.HIDDEN), "passwordsFile": S.PASSWORDS_FILE}


# ---- whole-book reads, the column upgrade, rows placed by hand -----------------
#
# These use the Settings last given to use_settings() (or an upload/recompile).


def use_settings(settings: dict) -> None:
    _state["config"] = _config(settings, {})


def _ids(sheet_ids: dict) -> dict[str, int]:
    return {k: int(v) for k, v in sheet_ids.items()}


def book_ranges(year: int, titles: list[str]) -> list[str]:
    """Every month and trip tab's rows, to find a row by key anywhere in the book."""
    months, trips = sheetplan.month_and_trip_tabs(list(titles), int(year), _state["config"])
    return sheetplan.data_ranges(months, trips)


def upgrade_headers(year: int, titles: list[str]) -> list[str]:
    return sheetplan.header_ranges(int(year), list(titles), _state["config"])


def upgrade_columns(sheet_ids: dict, headers: dict) -> dict:
    """Which tabs still have the old columns, and the column inserts for them."""
    old = sheetplan.old_tabs(headers)
    return {
        "old": old,
        "requests": sheetplan.insert_columns(_ids(sheet_ids), old),
        "finish": old + sheetplan.unfinished_tabs(headers),  # then upgrade_finish these
        "trips": sheetplan.trip_versions(headers),  # then upgrade_trips these
    }


def upgrade_finish(sheet_ids: dict, old: list[str], values: dict) -> dict:
    """After the inserts: headers, summaries, formats, Source and Remarks.
    Call recompile() first so the rows' Source and statement text are known."""
    compiled = _state.get("compiled")
    rows = compiled.rows if compiled else []
    clear, data, requests = sheetplan.upgrade_finish(_ids(sheet_ids), list(old), values, rows, _state["config"])
    return {"clear": clear, "data": data, "requests": requests}


def take_row(key: str, values: dict, sheet_ids: dict) -> dict:
    """A row as fields plus the request removing it, to move it elsewhere."""
    row, requests = sheetplan.take_row(key, values, _ids(sheet_ids))
    if row and row.get("date"):
        row["date"] = row["date"].isoformat()
    return {"row": row, "requests": requests}


def place_target(target: str, day: str) -> dict:
    """Where a row goes (title, its spreadsheet's year): a trip by name, else
    the month of its date."""
    trip = next((t for t in _state["config"].trips if t.name == target), None)
    if trip:
        return {"title": trip.name, "trip": True, "year": trip.start.year,
                "currencies": [c for c, _ in trip.currencies()]}
    d = date.fromisoformat(day[:10])
    return {"title": month_title(d.year, d.month), "trip": False, "year": d.year, "currencies": []}


def layout_cells() -> dict:
    """Cells the app reads directly."""
    from .accounts import TRIP_TOTAL_CELL, TRIPS_CELL

    return {"trips": TRIPS_CELL, "tripTotal": TRIP_TOTAL_CELL}


def prepare_rows(year: int, titles: list[str], rows: list[dict], target: str, created: bool = False) -> dict:
    """Put `rows` (fields as in take_row) on `target`, a trip name or a month
    title; with no rows, just make sure the tab exists. Then finish_rows()."""
    config = _state["config"]
    account_rows = [
        AccountRow(
            kind=r["kind"], date=date.fromisoformat(str(r["date"])[:10]), item=r.get("item", ""),
            amount=round(abs(float(r.get("amount") or 0)), 2), remarks=r.get("remarks", ""), key=r["key"],
            category=r.get("category", "") if r["kind"] == "spend" else "",
            importance=r.get("importance", "") if r["kind"] == "spend" else "", source=r.get("source", ""),
        )
        for r in rows
    ]
    trip = next((t for t in config.trips if t.name == target), None)
    if trip:
        tabs = [Tab(trip.name, "trip", (trip.start.year, trip.start.month, 1, trip.name), list(account_rows), trip)]
        y, m = deduction_month(trip)
        tabs.append(Tab(month_title(y, m), "month", (y, m, 0, "")))  # its total comes off this month
    else:
        y, m = parse_month_title(target)
        tabs = [Tab(target, "month", (y, m, 0, ""), list(account_rows))]
    tabs = sorted((t for t in tabs if t.order[0] == int(year)), key=lambda t: t.order)
    _state["placed"] = tabs
    prepared = sheetplan.prepare(int(year), list(titles), tabs, config, created)
    _state.setdefault("prepared", {})[int(year)] = prepared
    return {"add": [asdict(t) for t in prepared.add], "delete": prepared.delete, "reads": prepared.reads,
            "widths": prepared.widths}


def finish_rows(year: int, sheet_ids: dict, values: dict) -> dict:
    done = sheetplan.finish(int(year), _state["prepared"][int(year)], _ids(sheet_ids), values, _state["placed"],
                            _state["config"], to_update=False)
    return {"clear": done.clear, "data": done.data, "requests": done.requests, "added": done.added}


def _trip(name: str):
    trip = next((t for t in _state["config"].trips if t.name == name), None)
    if trip is None:
        raise ValueError(f'No trip called "{name}" in Settings › Trips.')
    return trip


def _currency_index(trip, currency: str) -> int:
    codes = [c.strip().upper() for c, _ in trip.currencies()]
    want = (currency or "").strip().upper()
    if want not in codes:
        raise ValueError(f'{trip.name} has no {currency} block: add {currency} to the trip in Settings › Trips.')
    return codes.index(want)


def cash_ranges(trip_title: str, currency: str) -> list[str]:
    from .accounts import currency_cols

    c = currency_cols(_currency_index(_trip(trip_title), currency))
    return [f"{sheetplan.quote(trip_title)}!{c[0]}4:{c[-1]}"]


def cash_row(values: list[list], trip_title: str, fields: dict, currency: str) -> list[dict]:
    return sheetplan.cash_row(values or [], trip_title, fields, _currency_index(_trip(trip_title), currency))


def paid_ranges(trip_title: str) -> list[str]:
    from .accounts import PAID_COLS, PAID_KEY

    return [f"{sheetplan.quote(trip_title)}!{PAID_COLS[0]}4:{PAID_KEY}"]


def paid_row(values: list[list], trip_title: str, fields: dict) -> list[dict]:
    return sheetplan.paid_row(values or [], trip_title, fields)


def trip_refresh(sheet_ids: dict) -> dict:
    data, requests = sheetplan.trip_refresh(_ids(sheet_ids), _state["config"])
    return {"data": data, "requests": requests}


def trips() -> list[dict]:
    return [{"name": t.name, "currencies": [c for c, _ in t.currencies()], "start": t.start.isoformat(),
             "end": t.end.isoformat()} for t in _state["config"].trips]


def old_accounts(files: list[dict], before: str = "") -> dict:
    """An accounts workbook kept by hand (template layout), as files[0]:
    months (each a list of rows), trips and your own tabs, to place with
    prepare_rows/finish_rows, trip_extras and custom_add_many. `before`
    ("2026-08"): leave out that month on (your statements cover it) and the
    trips in it."""
    from .old_accounts import rows_from_workbook, sheets_from_workbook, trips_from_workbook

    data = bytes(files[0]["data"])
    months = rows_from_workbook(data)
    trips = trips_from_workbook(data)
    skipped = []
    if before:
        def ym(title):
            y, m = parse_month_title(title)
            return f"{y}-{m:02d}"
        skipped = [t for t in months if ym(t) >= before] + [t["name"] for t in trips if t["end"][:7] >= before]
        months = {t: rows for t, rows in months.items() if ym(t) < before}
        trips = [t for t in trips if t["end"][:7] < before]
    return {
        "months": months, "years": {t: parse_month_title(t)[0] for t in months},
        "trips": trips,  # [{name, currencies: [{code, rate}], start, end, year, rm, paid, cash: {code: rows}, received}]
        "sheets": sheets_from_workbook(data, {t["name"] for t in trips_from_workbook(data)}),
        "skipped": skipped,
    }


TRIP_BLOCK_FIELDS = {
    "paid": ["date", "item", "amount", "remarks", "key"],
    "cash": ["date", "item", "category", "amount", "importance", "remarks"],
    "received": ["date", "item", "currency", "amount", "remarks"],
}


def trip_extra_ranges(trip_title: str) -> list[dict]:
    """[{block, currency, range}] of a trip tab's blocks other than RM spending."""
    from .accounts import PAID_COLS, PAID_KEY, currency_cols, received_cols

    trip = _trip(trip_title)
    q = sheetplan.quote(trip_title)
    out = [{"block": "paid", "currency": "", "range": f"{q}!{PAID_COLS[0]}4:{PAID_KEY}"}]
    for i, (code, _) in enumerate(trip.currencies()):
        c = currency_cols(i)
        out.append({"block": "cash", "currency": code, "range": f"{q}!{c[0]}4:{c[-1]}"})
    if trip.currencies():
        rc = received_cols(len(trip.currencies()))
        out.append({"block": "received", "currency": "", "range": f"{q}!{rc[0]}4:{rc[-1]}"})
    return out


def trip_extras(trip_title: str, now: list[list[list]], paid: list[dict], cash: dict, received: list[dict]) -> list[dict]:
    """Rows for the trip's other blocks (in trip_extra_ranges order; `now` is
    what each block holds) that aren't there yet, written under what's there.
    Matched by date, item and amount, so a second import adds nothing."""
    from .sheetplan import as_amount, as_date, cell

    def ident(d, item, amount):
        day = as_date(d) if d not in ("", None) else None
        return (day.isoformat() if day else "", str(item).strip(), as_amount(amount))

    out = []
    for spec, have_rows in zip(trip_extra_ranges(trip_title), now):
        block = spec["block"]
        fields = TRIP_BLOCK_FIELDS[block]
        rows = paid if block == "paid" else received if block == "received" else (cash or {}).get(spec["currency"], [])
        amount_i = fields.index("amount")
        item_i = fields.index("item")
        have = [ident(r[0] if r else "", r[item_i] if len(r) > item_i else "", r[amount_i] if len(r) > amount_i else 0)
                for r in (have_rows or [])]
        fresh = []
        for r in rows:
            k = ident(r.get("date", ""), r.get("item", ""), r.get("amount", 0))
            if k in have:
                have.remove(k)  # one existing row covers one imported row
                continue
            fresh.append([(as_date(r["date"]).isoformat() if r.get("date") else "") if f == "date" else
                          (round(float(r.get(f) or 0), 2) if f == "amount" else cell(r.get(f, ""))) for f in fields])
        if fresh:
            col0, rest = spec["range"].split("!")[1].split(":")
            first_col = "".join(ch for ch in col0 if ch.isalpha())
            last_col = rest
            start = 4 + len(have_rows or [])
            out.append({"range": f"{spec['range'].split('!')[0]}!{first_col}{start}:{last_col}{start + len(fresh) - 1}",
                        "values": fresh})
    return out


def upgrade_trip_ranges(trips: dict) -> list[str]:
    """Rows of the trip tabs being rebuilt (trips: {title: version})."""
    return [f"{sheetplan.quote(t)}!A4:AZ" for t in trips]


def upgrade_trips(year: int, titles: list[str], sheet_ids: dict, trips: dict, values: dict) -> dict:
    """Trip tabs in an older layout rewritten in the current one, then every
    month's Trips/Final and the Year End Summary. Call recompile() first."""
    compiled = _state.get("compiled")
    by_key = {r.key: r for r in compiled.rows} if compiled else {}
    config = _state["config"]
    clear, data, requests = [], [], []
    for title, version in trips.items():
        trip = next((t for t in config.trips if t.name == title), None)
        if trip is None:
            continue
        rng = f"{sheetplan.quote(title)}!A4:AZ"
        c, d, r = sheetplan.trip_rebuild(trip, version, values.get(rng, []), by_key, config, int(sheet_ids[title]))
        clear += c
        data += d
        requests += r
    data += sheetplan.links_plan(int(year), list(titles), config)
    return {"clear": clear, "data": data, "requests": requests}


# ---- custom sheets (Sheets section) ------------------------------------------------
# Use the Settings last given to use_settings(). Sheets are {"name", "year",
# "counts", "tables": [{"name", "currency", "label"}]}.


def _sheet(name: str):
    sheet = next((s for s in _state["config"].sheets if s.name == name), None)
    if sheet is None:
        raise ValueError(f'No sheet called "{name}" in Settings › Sheets.')
    return sheet


def sheets_list() -> list[dict]:
    return [asdict(s) for s in _state["config"].sheets]


def sheets_rows(sheets: list[dict]) -> list[list]:
    """Settings › Sheets body (no header) for this list of sheets."""
    from .config import CustomSheet, CustomTable
    from .custom import encode_tables

    out = []
    for s in sheets:
        tables = [CustomTable(t["name"].strip(), (t.get("currency") or "RM").strip(), (t.get("label") or "Item").strip())
                  for t in s.get("tables", []) if t.get("name", "").strip()]
        sheet = CustomSheet(s["name"].strip(), int(s["year"]), s.get("counts", ""), tables)
        out.append([sheet.name, sheet.year, sheet.counts, encode_tables(sheet.tables)])
    return out


def custom_ranges(name: str) -> list[str]:
    from . import custom

    return custom.data_ranges(_sheet(name))


def custom_rows(name: str, values: dict) -> list[dict]:
    from . import custom

    return custom.rows(_sheet(name), values)


def custom_add(name: str, table: int, existing: list[list], fields: dict) -> list[dict]:
    from . import custom

    return custom.append(_sheet(name), int(table), existing or [], fields)


def custom_add_many(name: str, table: int, existing: list[list], rows: list[dict]) -> list[dict]:
    from . import custom

    return custom.append_many(_sheet(name), int(table), existing or [], rows)


def custom_edit(name: str, values: dict, key: str, fields: dict) -> list[dict]:
    from . import custom

    return custom.edit(_sheet(name), values, key, fields)


def custom_remove(name: str, sheet_id: int, values: dict, key: str) -> list[dict]:
    from . import custom

    return custom.remove(_sheet(name), int(sheet_id), values, key)


def custom_setup(name: str, sheet_id: int) -> dict:
    """Headers, totals and formats of a custom sheet's tab (made or changed)."""
    from . import custom

    sheet = _sheet(name)
    q = sheetplan.quote(sheet.name)
    return {"data": [{"range": f"{q}!{c}", "values": [[v]]} for c, v in custom.layout(sheet).items()],
            "requests": custom.formats(int(sheet_id), sheet)}


def year_summary(year: int, titles: list[str]) -> list[dict]:
    """The Year End Summary cells, e.g. after a custom sheet is added."""
    from .accounts import YEAR_SUMMARY, year_summary_cells
    from .custom import summary_refs

    config = _state["config"]
    months, trips = sheetplan.month_and_trip_tabs(list(titles), int(year), config)
    cells = year_summary_cells(months, trips, *summary_refs(config.sheets, set(titles), int(year)))
    return [{"range": f"{sheetplan.quote(YEAR_SUMMARY)}!{c}", "values": [[v]]} for c, v in cells.items()]


# ---- Home and Trips screens (overview.py) ------------------------------------------


def year_ranges(year: int, titles: list[str]) -> list[str]:
    return overview.year_ranges(int(year), list(titles))


def year_totals(year: int, titles: list[str], values: list[list[list]]) -> dict:
    return overview.year_totals(int(year), list(titles), values)


def trip_range(name: str) -> str:
    return overview.trip_range(_trip(name))


def trip_detail(name: str, values: list[list]) -> dict:
    return overview.trip_detail(_trip(name), values or [])

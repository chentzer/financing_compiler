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
from . import sheetplan
from .accounts import AccountRow, Tab, deduction_month, month_title, parse_month_title
from .pipeline import Compiled, compile_statements
from .suggest import suggest_categories

_state: dict = {}


def _config(settings: dict, passwords: dict | None):
    return S.config_from_tabs(settings or {}, passwords or {})


def compile_upload(files: list[dict], settings: dict, passwords: dict, ledger: list[list]) -> dict:
    """files: [{"name": str, "data": bytes}]. settings: {tab: rows} of the
    Settings sheet. ledger: the Ledger tab's rows (header first)."""
    config = _config(settings, passwords)
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
        return {"title": trip.name, "trip": True, "year": trip.start.year, "currency": trip.currency}
    d = date.fromisoformat(day[:10])
    return {"title": month_title(d.year, d.month), "trip": False, "year": d.year, "currency": ""}


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
    return {"add": [asdict(t) for t in prepared.add], "delete": prepared.delete, "reads": prepared.reads}


def finish_rows(year: int, sheet_ids: dict, values: dict) -> dict:
    done = sheetplan.finish(int(year), _state["prepared"][int(year)], _ids(sheet_ids), values, _state["placed"],
                            _state["config"], to_update=False)
    return {"clear": done.clear, "data": done.data, "requests": done.requests, "added": done.added}


def cash_ranges(trip_title: str) -> list[str]:
    c = sheetplan.CASH_COLS
    return [f"{sheetplan.quote(trip_title)}!{c[0]}4:{c[-1]}"]


def cash_row(values: list[list], trip_title: str, fields: dict) -> list[dict]:
    return sheetplan.cash_row(values or [], trip_title, fields)


def trip_refresh(sheet_ids: dict) -> dict:
    data, requests = sheetplan.trip_refresh(_ids(sheet_ids), _state["config"])
    return {"data": data, "requests": requests}


def trips() -> list[dict]:
    return [{"name": t.name, "currency": t.currency, "start": t.start.isoformat(), "end": t.end.isoformat()}
            for t in _state["config"].trips]

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

from . import settings as S
from . import sheetplan
from .pipeline import Compiled, compile_statements

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
    return [f"{q}!A4:G"] if trip else [f"{q}!A3:G", f"{q}!N3:R"]


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


def settings_template() -> dict:
    """Tabs for a brand-new Settings sheet (defaults), plus which to hide."""
    tabs = S.tabs_from_config(_config({}, {}))
    tabs[S.REMOVED] = [S.HEADERS[S.REMOVED]]
    tabs[S.LEDGER] = [S.HEADERS[S.LEDGER]]
    return {"title": S.SETTINGS_TITLE, "tabs": tabs, "hidden": sorted(S.HIDDEN), "passwordsFile": S.PASSWORDS_FILE}

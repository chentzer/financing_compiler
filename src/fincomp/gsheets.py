"""Upload the accounts to Google Sheets, one spreadsheet per year.

Re-running is safe: each uploaded row carries a hidden key (columns G and R),
and only new transactions are appended. Rows already in the sheet are only
touched to write your own answers from the To Update cards (just the cells
you answered), or removed when you said a row isn't yours. Your edits,
hand-entered rows (cash, yen spending on a trip) and tabs fincomp doesn't
manage (e.g. "Chinese New Year") stay as they are; new tabs are slotted in
without moving yours.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import sheetplan
from .accounts import Tab
from .config import Config, GoogleConfig

SCOPES = [
    # Only files this app creates (the Sheets API accepts it too); it can't
    # see or open your other spreadsheets or the rest of your Drive.
    "https://www.googleapis.com/auth/drive.file",
    # The app's private App Data folder, where statement passwords are kept.
    "https://www.googleapis.com/auth/drive.appdata",
]


class UploadError(Exception):
    pass


@dataclass
class YearResult:
    title: str
    url: str
    added: int
    already: int
    to_update: int = 0  # cards still open
    fixed_in_sheet: int = 0  # cards you closed by editing the month tab


def connect(g: GoogleConfig):
    try:
        import gspread
    except ImportError as e:
        raise UploadError('Google upload needs gspread: pip install -e ".[google]"') from e
    if not g.credentials.exists():
        raise UploadError(
            f"No Google OAuth client at {g.credentials}. "
            "See 'Google Sheets setup' in README.md (one-time)."
        )
    g.token.parent.mkdir(parents=True, exist_ok=True)
    # Opens a browser for sign-in the first time, then reuses the token.
    return gspread.oauth(
        scopes=SCOPES,
        credentials_filename=str(g.credentials),
        authorized_user_filename=str(g.token),
    )


def upload(
    tabs_by_year: dict[int, list[Tab]], config: Config, answers: dict[str, dict] | None = None
) -> list[YearResult]:
    """Sync each year. Marks the answers it wrote as synced; save them after."""
    from google.auth.exceptions import RefreshError

    answers = {} if answers is None else answers
    gc = connect(config.google)
    results = []
    for year, tabs in tabs_by_year.items():
        try:
            results.append(_sync_year(gc, year, tabs, config, answers))
        except RefreshError:
            # Saved sign-in expired or was revoked (Google expires them after
            # 7 days for apps in Testing mode): sign in again and retry.
            config.google.token.unlink(missing_ok=True)
            gc = connect(config.google)
            results.append(_sync_year(gc, year, tabs, config, answers))
    return results


# ---- sync: run sheetplan's plan with gspread ----------------------------------


def _sync_year(gc, year: int, tabs: list[Tab], config: Config, answers: dict[str, dict]) -> YearResult:
    import gspread

    title = config.google.spreadsheet.replace("{year}", str(year))
    created = False
    try:
        sh = gc.open(title)
    except gspread.SpreadsheetNotFound:
        sh = gc.create(title, folder_id=config.google.folder_id or None)
        created = True

    _upgrade_columns(sh, year, tabs, config)
    sheets = {ws.title: ws for ws in sh.worksheets()}
    prepared = sheetplan.prepare(year, [ws.title for ws in sh.worksheets()], tabs, config, created)
    for t in prepared.add:
        sheets[t.title] = sh.add_worksheet(t.title, rows=t.rows, cols=t.cols, index=t.index)
    for t in prepared.delete:
        sh.del_worksheet(sheets.pop(t))

    got = sh.values_batch_get(prepared.reads, params={"valueRenderOption": "FORMULA"}).get("valueRanges", [])
    values = {rng: vr.get("values", []) for rng, vr in zip(prepared.reads, got)}
    done = sheetplan.finish(year, prepared, {t: ws.id for t, ws in sheets.items()}, values, tabs, config, answers)

    for rng in done.clear:
        sh.values_clear(rng)
    if done.data:
        sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": done.data})
    if done.requests:
        sh.batch_update({"requests": done.requests})
    for key in done.synced_keys:
        answers[key]["synced"] = True
    return YearResult(title=title, url=sh.url, added=done.added, already=done.already,
                      to_update=done.to_update, fixed_in_sheet=done.fixed_in_sheet)


def _upgrade_columns(sh, year: int, tabs: list[Tab], config: Config) -> None:
    """Tabs made before the Source and gap columns get them (sheetplan.upgrade_finish)."""
    titles = [ws.title for ws in sh.worksheets()]
    headers = sheetplan.header_ranges(year, titles, config)
    if not headers:
        return
    got = sh.values_batch_get(headers).get("valueRanges", [])
    head = {rng: vr.get("values", []) for rng, vr in zip(headers, got)}
    old = sheetplan.old_tabs(head)
    ids = {ws.title: ws.id for ws in sh.worksheets()}
    rows = [r for tab in tabs for r in tab.rows]
    for title, version in sheetplan.trip_versions(head).items():
        trip = next((t for t in config.trips if t.name == title), None)
        if trip is None:
            continue
        rng = f"{sheetplan.quote(title)}!A4:AZ"
        got = sh.values_batch_get([rng], params={"valueRenderOption": "FORMULA"}).get("valueRanges", [{}])
        clear, data, requests = sheetplan.trip_rebuild(trip, version, got[0].get("values", []),
                                                       {r.key: r for r in rows}, config, ids[title])
        for c in clear:
            sh.values_clear(c)
        sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})
        sh.batch_update({"requests": requests})
    if not old:
        return
    sh.batch_update({"requests": sheetplan.insert_columns(ids, old)})
    months, trips = sheetplan.month_and_trip_tabs(titles, year, config)
    reads = sheetplan.data_ranges(months, trips)
    got = sh.values_batch_get(reads, params={"valueRenderOption": "FORMULA"}).get("valueRanges", [])
    values = {rng: vr.get("values", []) for rng, vr in zip(reads, got)}
    clear, data, requests = sheetplan.upgrade_finish(ids, old, values, rows, config)
    for rng in clear:
        sh.values_clear(rng)
    if data:
        sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": data})
    if requests:
        sh.batch_update({"requests": requests})


# ---- one-time: config.toml -> Drive, for the website and phone app -------------


def push_settings(config: Config, ask_pin, ledger: list | None = None) -> str:
    """Create or refresh the "fincomp Settings" sheet from config.toml, put
    the statement passwords (encrypted with your PIN) in the Drive App Data
    folder, and (optionally) seed the Ledger with already-parsed
    transactions. `ask_pin(creating: bool) -> str` gets the PIN. Returns the
    sheet URL."""
    import json

    import gspread
    from google.auth.transport.requests import AuthorizedSession

    from . import settings as S
    from . import vault as V

    gc = connect(config.google)
    try:
        sh = gc.open(S.SETTINGS_TITLE)
    except gspread.SpreadsheetNotFound:
        sh = gc.create(S.SETTINGS_TITLE, folder_id=config.google.folder_id or None)

    tabs = S.tabs_from_config(config)
    sheets = {ws.title: ws for ws in sh.worksheets()}
    if S.REMOVED not in sheets:
        tabs[S.REMOVED] = [S.HEADERS[S.REMOVED]]
    if ledger is not None:
        tabs[S.LEDGER] = S.ledger_rows(ledger)
    elif S.LEDGER not in sheets:
        tabs[S.LEDGER] = [S.HEADERS[S.LEDGER]]
    placeholder = next(iter(sheets)) if len(sheets) == 1 and next(iter(sheets)) not in S.TABS else None

    for title, rows in tabs.items():
        ws = sheets.get(title) or sh.add_worksheet(title, rows=max(len(rows) + 50, 100), cols=12)
        ws.clear()
        ws.update(rows, "A1", value_input_option="RAW")
        if title in S.HIDDEN:
            sh.batch_update({"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "hidden": True}, "fields": "hidden"}}]})
    if placeholder:
        sh.del_worksheet(sheets[placeholder])

    # Passwords: encrypted with the PIN (vault.py), one file in the App Data
    # folder. Merged into what's already there; the old readable file goes.
    session = AuthorizedSession(gc.http_client.auth)

    def find(name: str) -> list[dict]:
        return session.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"spaces": "appDataFolder", "q": f"name = '{name}'", "fields": "files(id)"},
        ).json().get("files", [])

    found = find(V.VAULT_FILE)
    mine = {k: v for k, v in config.passwords.items() if v}
    if found:
        current = session.get(f"https://www.googleapis.com/drive/v3/files/{found[0]['id']}?alt=media").json()
        pin = ask_pin(False)
        merged = {**V.open_vault(current, pin), **mine}  # raises WrongPin
        blob = V.seal(merged, pin, salt=V.salt_of(current))
    else:
        blob = V.seal(mine, ask_pin(True))  # a new random salt
    body = json.dumps(blob)
    if found:
        url = f"https://www.googleapis.com/upload/drive/v3/files/{found[0]['id']}?uploadType=media"
        session.patch(url, data=body, headers={"Content-Type": "application/json"}).raise_for_status()
    else:
        meta = json.dumps({"name": V.VAULT_FILE, "parents": ["appDataFolder"]})
        boundary = "fincomp-boundary"
        crlf = "\r\n"
        multipart = crlf.join([
            f"--{boundary}", "Content-Type: application/json; charset=UTF-8", "", meta,
            f"--{boundary}", "Content-Type: application/json", "", body,
            f"--{boundary}--",
        ])
        session.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            data=multipart.encode(), headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        ).raise_for_status()
    for old in find(V.LEGACY_FILE):
        session.delete(f"https://www.googleapis.com/drive/v3/files/{old['id']}").raise_for_status()
    return sh.url

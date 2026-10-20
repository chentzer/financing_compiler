"""Custom sheets: tabs of your own in a year's spreadsheet, made in the app's
Sheets section (e.g. "Chinese New Year": ang pao in RM and in SGD).

Each table takes 6 columns, side by side from A:
    Date | <label> | Amount (<currency>) | Remarks | key (hidden) | gap
Row 1 has the table's name and its total; row 2 the headers; rows from 3.
Rows added in the app get "m-..." keys so they can be edited and removed.
RM tables of a sheet that counts as earnings or spending feed the Year End
Summary.

Pure plans, like sheetplan.py: values in, requests out.
"""

from __future__ import annotations

import uuid

from .accounts import COLOURS, quote
from .config import CustomSheet, CustomTable

TABLE_WIDTH = 6
FIRST_ROW = 3
TAB_ROWS = 1000


def _letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def table_cols(i: int) -> list[str]:
    """Date, label, amount, remarks, key columns of table i."""
    return [_letter(i * TABLE_WIDTH + k) for k in range(5)]


def is_rm(currency: str) -> bool:
    return currency.strip().upper() in ("", "RM", "MYR")


def total_cell(i: int) -> str:
    return f"{table_cols(i)[2]}1"


def layout(sheet: CustomSheet) -> dict[str, object]:
    cells: dict[str, object] = {}
    for i, t in enumerate(sheet.tables):
        c = table_cols(i)
        cur = t.currency.strip() or "RM"
        cells[f"{c[0]}1"] = t.name
        cells[f"{c[1]}1"] = "Total"
        cells[f"{c[2]}1"] = f"=SUM(${c[2]}${FIRST_ROW}:${c[2]})"
        for col, h in zip(c, ["Date", t.label or "Item", f"Amount ({cur})", "Remarks", "Key"]):
            cells[f"{col}2"] = h
    return cells


def formats(sheet_id: int, sheet: CustomSheet) -> list[dict]:
    colour = COLOURS["earn" if sheet.counts == "earnings" else "spend" if sheet.counts == "spending" else "summary"]

    def col(i: int, **props) -> dict:
        return {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": props, "fields": ",".join(props)}}

    def cells(r0: int, r1: int | None, c0: int, c1: int, fmt: dict, fields: str) -> dict:
        rng = {"sheetId": sheet_id, "startRowIndex": r0, "startColumnIndex": c0, "endColumnIndex": c1}
        if r1 is not None:
            rng["endRowIndex"] = r1
        return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": fmt}, "fields": fields}}

    reqs = [{"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 2}},
                                       "fields": "gridProperties.frozenRowCount"}}]
    for i, t in enumerate(sheet.tables):
        base = i * TABLE_WIDTH
        money = "#,##0.00"
        reqs += [
            cells(FIRST_ROW - 1, None, base, base + 1, {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}},
                  "userEnteredFormat.numberFormat"),
            cells(0, None, base + 2, base + 3, {"numberFormat": {"type": "NUMBER", "pattern": money}},
                  "userEnteredFormat.numberFormat"),
            cells(0, 2, base, base + 4, {"backgroundColor": colour, "textFormat": {"bold": True}},
                  "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold"),
            col(base + 1, pixelSize=200), col(base + 3, pixelSize=200),
            col(base + 4, hiddenByUser=True), col(base + 5, pixelSize=24),
        ]
    return reqs


def data_ranges(sheet: CustomSheet) -> list[str]:
    q = quote(sheet.name)
    return [f"{q}!{c[0]}{FIRST_ROW}:{c[4]}" for c in (table_cols(i) for i in range(len(sheet.tables)))]


def rows(sheet: CustomSheet, values: dict[str, list[list]]) -> list[dict]:
    """Each table with its rows (as read with UNFORMATTED_VALUE)."""
    from .sheetplan import as_amount, as_date

    out = []
    for i, (t, rng) in enumerate(zip(sheet.tables, data_ranges(sheet))):
        found = []
        for n, r in enumerate(values.get(rng, [])):
            r = list(r) + [""] * 5
            if not any(str(v).strip() for v in r[:4]):
                continue
            d = as_date(r[0]) if r[0] not in ("", None) else None
            found.append({"row": FIRST_ROW + n, "date": d.isoformat() if d else "", "item": str(r[1]),
                          "amount": as_amount(r[2]), "remarks": str(r[3]), "key": str(r[4])})
        out.append({"index": i, "name": t.name, "currency": t.currency or "RM", "label": t.label or "Item",
                    "total": round(sum(x["amount"] for x in found), 2), "rows": found})
    return out


def new_key() -> str:
    return "m-" + uuid.uuid4().hex[:12]


def _values(fields: dict) -> list:
    from .sheetplan import as_date, cell

    day = as_date(fields.get("date", "")) if fields.get("date") else None
    return [day.isoformat() if day else "", cell(fields.get("item", "")), round(float(fields.get("amount") or 0), 2),
            cell(fields.get("remarks", "")), fields.get("key") or new_key()]


def append(sheet: CustomSheet, table: int, existing: list[list], fields: dict) -> list[dict]:
    """values:batchUpdate data writing one row under the table's last row."""
    c = table_cols(table)
    row = FIRST_ROW + len(existing)
    return [{"range": f"{quote(sheet.name)}!{c[0]}{row}:{c[4]}{row}", "values": [_values(fields)]}]


def append_many(sheet: CustomSheet, table: int, existing: list[list], rows_: list[dict]) -> list[dict]:
    """Rows (with keys) not already in the table, written under its last row."""
    have = {str(r[4]) for r in existing if len(r) > 4 and r[4]}
    fresh = [r for r in rows_ if r.get("key") not in have]
    if not fresh:
        return []
    c = table_cols(table)
    row = FIRST_ROW + len(existing)
    return [{"range": f"{quote(sheet.name)}!{c[0]}{row}:{c[4]}{row + len(fresh) - 1}",
             "values": [_values(r) for r in fresh]}]


def _find(sheet: CustomSheet, values: dict[str, list[list]], key: str) -> tuple[int, int] | None:
    for i, rng in enumerate(data_ranges(sheet)):
        for n, r in enumerate(values.get(rng, [])):
            if len(r) > 4 and str(r[4]) == key:
                return i, FIRST_ROW + n
    return None


def edit(sheet: CustomSheet, values: dict[str, list[list]], key: str, fields: dict) -> list[dict]:
    from .sheetplan import as_date, cell

    found = _find(sheet, values, key)
    if not found:
        return []
    i, row = found
    c = table_cols(i)
    out = []
    for name, col in zip(("date", "item", "amount", "remarks"), c[:4]):
        if name not in fields or fields[name] is None:
            continue
        v = fields[name]
        if name == "date":
            v = (as_date(v).isoformat() if as_date(v) else "") if v else ""
        elif name == "amount":
            v = round(float(v or 0), 2)
        else:
            v = cell(v)
        out.append({"range": f"{quote(sheet.name)}!{col}{row}", "values": [[v]]})
    return out


def remove(sheet: CustomSheet, sheet_id: int, values: dict[str, list[list]], key: str) -> list[dict]:
    found = _find(sheet, values, key)
    if not found:
        return []
    i, row = found
    base = i * TABLE_WIDTH
    return [{"deleteRange": {"range": {"sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                                       "startColumnIndex": base, "endColumnIndex": base + 5},
                             "shiftDimension": "ROWS"}}]


def summary_refs(sheets: list[CustomSheet], titles: set[str], year: int) -> tuple[list[str], list[str]]:
    """Cells to add to the Year End Summary: (earnings, spending)."""
    earn, spend = [], []
    for s in sheets:
        if s.year != year or s.name not in titles or s.counts not in ("earnings", "spending"):
            continue
        refs = [f"{quote(s.name)}!{total_cell(i)}" for i, t in enumerate(s.tables) if is_rm(t.currency)]
        (earn if s.counts == "earnings" else spend).extend(refs)
    return earn, spend


# ---- Settings › Sheets tab ------------------------------------------------------------
# Name | Year | Counts as | Tables ("Ang Pao (RM) / RM / Person ; Ang Pao (SGD) / SGD / Person")


def encode_tables(tables: list[CustomTable]) -> str:
    return " ; ".join(f"{t.name} / {t.currency or 'RM'} / {t.label or 'Item'}" for t in tables)


def decode_tables(text: str) -> list[CustomTable]:
    out = []
    for part in str(text).split(";"):
        bits = [b.strip() for b in part.split("/")]
        if bits and bits[0]:
            out.append(CustomTable(bits[0], (bits[1] if len(bits) > 1 else "") or "RM",
                                   (bits[2] if len(bits) > 2 else "") or "Item"))
    return out

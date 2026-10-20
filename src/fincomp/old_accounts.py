"""Bring in accounts you kept by hand before fincomp: an .xlsx in the
template's layout ("2022 Accounts.xlsx": month tabs with Spendings and
Earnings blocks under a header row of Date, Item, ...).

Rows are copied as they are (Item, Category, Importance, Amount, Remarks;
Source if the workbook has it) into the month tab of the same name, as rows
you added yourself. Each gets a key from its contents, so importing the same
workbook again adds nothing twice. Pivot tables and summaries in the old
workbook are not copied: the new tabs have their own formulas.

Read with zipfile + xml only (no openpyxl), so it runs in the browser.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter
from datetime import date, timedelta
from xml.etree import ElementTree as ET

from .accounts import parse_month_title

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
EXCEL_EPOCH = date(1899, 12, 30)
SPEND_FIELDS = {"date": "date", "item": "item", "category": "category", "amount (rm)": "amount", "amount": "amount",
                "importance": "importance", "source": "source", "remarks": "remarks"}
EARN_FIELDS = {"date": "date", "item": "item", "amount (rm)": "amount", "amount": "amount", "source": "source",
               "remarks": "remarks"}


def is_workbook(data: bytes) -> bool:
    if data[:2] != b"PK":
        return False
    try:
        return "xl/workbook.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return False


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheets(data: bytes) -> dict[str, dict[int, dict[int, object]]]:
    """{sheet title: {row number: {0-based column: value}}}. Numbers stay
    numbers (dates are Excel serials); formulas give their saved result."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("pr:Relationship", NS)}
    out = {}
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
        target = rels[sheet.get(f"{{{NS['r']}}}id")].lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        rows: dict[int, dict[int, object]] = {}
        for c in ET.fromstring(z.read(path)).iter(f"{{{NS['m']}}}c"):
            ref, kind = c.get("r"), c.get("t", "n")
            v = c.find("m:v", NS)
            if kind == "inlineStr":
                value: object = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
            elif v is None or v.text is None:
                continue
            elif kind == "s":
                value = shared[int(v.text)]
            elif kind in ("str", "e"):
                value = v.text
            elif kind == "b":
                value = v.text == "1"
            else:
                value = float(v.text)
            row = int(re.search(r"\d+", ref).group())
            rows.setdefault(row, {})[_col(ref)] = value
        out[sheet.get("name")] = rows
    return out


def _date(v) -> date | None:
    if isinstance(v, float):
        return EXCEL_EPOCH + timedelta(days=int(v))
    if isinstance(v, str):
        for fmt in (r"(\d{4})-(\d{1,2})-(\d{1,2})", r"(\d{1,2})/(\d{1,2})/(\d{4})"):
            if m := re.match(fmt, v.strip()):
                a, b, c = map(int, m.groups())
                return date(a, b, c) if a > 31 else date(c, b, a)
    return None


def _blocks(header: dict[int, object]) -> list[tuple[str, dict[str, int]]]:
    """[("spend", {field: column}), ("earn", ...)] from the header row: a
    block starts at each "Date" and runs over the names that follow."""
    starts = sorted(c for c, v in header.items() if str(v).strip().lower() == "date")
    blocks = []
    for n, start in enumerate(starts[:2]):
        kind = "spend" if n == 0 else "earn"
        names = SPEND_FIELDS if kind == "spend" else EARN_FIELDS
        cols, c = {}, start
        while c in header and (f := names.get(str(header[c]).strip().lower())) and f not in cols:
            cols[f] = c
            c += 1
        if {"date", "item", "amount"} <= cols.keys():
            blocks.append((kind, cols))
    return blocks


def rows_from_workbook(data: bytes) -> dict[str, list[dict]]:
    """{month tab title: [row fields]} for every month tab in the workbook."""
    out: dict[str, list[dict]] = {}
    for title, rows in read_sheets(data).items():
        if not parse_month_title(title):
            continue  # Format, Year End Summary, your own tabs
        header_row = next((r for r in sorted(rows) if r <= 5 and sum(
            str(v).strip().lower() == "date" for v in rows[r].values()) >= 1), None)
        if header_row is None:
            continue
        seen: Counter = Counter()
        found = []
        for kind, cols in _blocks(rows[header_row]):
            for r in sorted(k for k in rows if k > header_row):
                cells = rows[r]
                get = lambda f: cells.get(cols[f]) if f in cols else None  # noqa: E731
                when, amount = _date(get("date")), get("amount")
                if when is None or not isinstance(amount, float) or not amount:
                    continue
                row = {
                    "kind": kind, "date": when.isoformat(), "item": str(get("item") or "").strip(),
                    "amount": round(abs(amount), 2), "source": str(get("source") or "").strip(),
                    "remarks": str(get("remarks") or "").strip(),
                }
                if kind == "spend":
                    row["category"] = str(get("category") or "").strip()
                    row["importance"] = str(get("importance") or "").strip()
                ident = f"{title}|{kind}|{row['date']}|{row['item']}|{row['amount']:.2f}"
                seen[ident] += 1
                row["key"] = "m-" + hashlib.sha1(f"{ident}|{seen[ident]}".encode()).hexdigest()[:12]
                found.append(row)
        if found:
            out[title] = found
    return out

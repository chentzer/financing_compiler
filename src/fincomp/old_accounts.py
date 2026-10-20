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


def read_sheets(data: bytes, formulas: dict[str, set[tuple[int, int]]] | None = None
                ) -> dict[str, dict[int, dict[int, object]]]:
    """{sheet title: {row number: {0-based column: value}}}. Numbers stay
    numbers (dates are Excel serials); formulas give their saved result.
    `formulas`, if given, gets {title: {(row, column)}} of cells holding a SUM."""
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
            f = c.find("m:f", NS)
            if formulas is not None and f is not None and "SUM" in (f.text or "").upper():
                formulas.setdefault(sheet.get("name"), set()).add((row, _col(ref)))
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
        # Up to the next "Date" or a blank; columns it doesn't know (2025's
        # "Claimable") are skipped, not the end of the block.
        while c in header and str(header[c]).strip() and (c == start or str(header[c]).strip().lower() != "date"):
            f = names.get(str(header[c]).strip().lower())
            if f and f not in cols:
                cols[f] = c
            c += 1
        if {"date", "item", "amount"} <= cols.keys():
            blocks.append((kind, cols))
    return blocks


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def month_tabs(sheets: dict[str, dict[int, dict[int, object]]]) -> dict[str, str]:
    """{tab title: month title}. "September 2023" as it is; a tab named just
    "January" (2024's workbook) gets the year of its dates, or the year
    most of the workbook's dates are in."""
    def years_in(rows) -> list[int]:
        return [d.year for cells in rows.values() for v in cells.values()
                if isinstance(v, float) and 30000 < v < 60000 and (d := _date(v))]
    everything = Counter(y for rows in sheets.values() for y in years_in(rows))
    out = {}
    for title, rows in sheets.items():
        if parse_month_title(title):
            out[title] = title
        elif title.strip().lower() in MONTHS:
            ys = Counter(years_in(rows)) or everything
            if ys:
                out[title] = f"{title.strip().capitalize()} {ys.most_common(1)[0][0]}"
    return out


def rows_from_workbook(data: bytes) -> dict[str, list[dict]]:
    """{month tab title: [row fields]} for every month tab in the workbook."""
    out: dict[str, list[dict]] = {}
    sheets = read_sheets(data)
    months = month_tabs(sheets)
    for tab, rows in sheets.items():
        if tab not in months:
            continue  # Format, Year End Summary, trips, your own tabs
        title = months[tab]
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


def _formulas(data: bytes, title: str) -> list[str]:
    """Formulas on one sheet (to see what the old Year End Summary added up)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("pr:Relationship", NS)}
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
        if sheet.get("name") != title:
            continue
        target = rels[sheet.get(f"{{{NS['r']}}}id")].lstrip("/")
        root = ET.fromstring(z.read(target if target.startswith("xl/") else "xl/" + target))
        return [f.text or "" for f in root.iter(f"{{{NS['m']}}}f")]
    return []


def _amount_currency(header: object) -> str | None:
    """"Amount (Yen)" -> "Yen"; "Amount (RM)" -> "RM"; else None."""
    m = re.fullmatch(r"\s*amount\s*\(([^)]+)\)\s*", str(header), re.IGNORECASE)
    return m.group(1).strip() if m else None


def _starts(header: dict[int, object]) -> list[int]:
    return sorted(c for c, v in header.items() if str(v).strip().lower() == "date")


def _block(header: dict[int, object], start: int) -> list[str]:
    """Header names from `start` up to the next blank or "Date"."""
    names, c = [], start
    while c in header and str(header[c]).strip() and (c == start or str(header[c]).strip().lower() != "date"):
        names.append(str(header[c]).strip())
        c += 1
    return names


def _year(dates: list[date], fallback: int) -> int:
    return Counter(d.year for d in dates).most_common(1)[0][0] if dates else fallback


def _key(ident: str, seen: Counter) -> str:
    seen[ident] += 1
    return "m-" + hashlib.sha1(f"{ident}|{seen[ident]}".encode()).hexdigest()[:12]


def _old_rate(rows: dict[int, dict[int, object]], currency: str) -> float | None:
    """The rate the old trip sheet used: its "Total Spent in <currency>" and
    the RM it came to ("Total Spent in MYR (...)")."""
    spent = in_rm = None
    for cells in rows.values():
        for c, v in cells.items():
            label = str(v).strip().lower()
            value = cells.get(c + 1)
            if not isinstance(value, float):
                continue
            names = {currency.lower()} | {k for k, v in CURRENCY_NAMES.items() if v == currency.upper()}
            if currency and label in {f"total spent in {n}" for n in names}:
                spent = value
            elif label.startswith("total spent in myr (") or label.startswith("total spent in rm ("):
                in_rm = value
    return round(in_rm / spent, 6) if spent and in_rm else None


CURRENCY_NAMES = {"yen": "JPY", "euro": "EUR", "euros": "EUR", "pound": "GBP", "pounds": "GBP", "vtd": "VND",
                  "dong": "VND", "won": "KRW", "baht": "THB", "rupiah": "IDR", "peso": "PHP", "yuan": "CNY",
                  "rmb": "CNY", "ntd": "TWD", "nt$": "TWD"}
RM_NAMES = {"rm", "myr", "ringgit"}


def _code(currency: str) -> str:
    c = currency.strip()
    return CURRENCY_NAMES.get(c.lower(), c.upper() if len(c) <= 4 else c)


def _row1_info(rows: dict[int, dict[int, object]], title: str) -> tuple[date | None, date | None, float | None, bool]:
    """Start Date / End Date / Convertion Rate written in row 1 (2025 on), and
    whether row 1 names this trip (it was sometimes copied from another)."""
    cells = rows.get(1, {})
    start = end = rate = None
    for c, v in cells.items():
        label = str(v).strip().lower()
        nxt = cells.get(c + 1)
        if label == "start date":
            start = _date(nxt)
        elif label == "end date":
            end = _date(nxt)
        elif label.startswith("conver") and isinstance(nxt, float) and nxt > 0:
            rate = nxt
    named = str(cells.get(0, "")).strip().lower() == title.strip().lower()
    return start, end, rate, named


def trips_from_workbook(data: bytes) -> list[dict]:
    """Trip tabs (header in row 3): an RM spending block (Category, Amount (RM)
    or (MYR)), a spending block per foreign currency (with Category), and
    blocks without Category for money received: in RM/MYR it's what friends
    paid you back, in another currency it's money exchanged or left over.
    Dates and the rate come from row 1 when it has them (2025 on), else from
    the rows and the old summary."""
    sheets = read_sheets(data)
    months = month_tabs(sheets)
    years = [parse_month_title(t)[0] for t in months.values()]
    row1 = {t: _row1_info(rows, t) for t, rows in sheets.items() if t not in months}
    shared = Counter((s, e) for s, e, _, _ in row1.values() if s and e)
    out = []
    for title, rows in sheets.items():
        if title in months or 3 not in rows:
            continue
        header = rows[3]
        blocks = [(s, _block(header, s)) for s in _starts(header)]

        def amount_of(names):
            return next(((i, cur) for i, h in enumerate(names) if (cur := _amount_currency(h))), (None, None))

        rm = cash = None
        cash_blocks, paid_blocks, received_blocks = [], [], []
        for s, names in blocks:
            i, cur = amount_of(names)
            if i is None:
                continue
            is_rm = cur.strip().lower() in RM_NAMES
            if "Category" in names:
                if is_rm and rm is None:
                    rm = (s, names)
                elif not is_rm:
                    cash_blocks.append((s, names, _code(cur)))
            else:
                (paid_blocks if is_rm else received_blocks).append((s, names, _code(cur)))
        if not rm:
            continue

        def take(start: int, names: list[str], need_date: bool) -> list[dict]:
            found = []
            lower = [n.lower() for n in names]
            amount_i = next(i for i, h in enumerate(names) if _amount_currency(h))
            rm_i = next((i for i, h in enumerate(names) if i != amount_i and (_amount_currency(h) or "").lower() in RM_NAMES
                         or h.replace(" ", "").lower() == "amount(myr)" and i != amount_i), None)
            for r in sorted(k for k in rows if k > 3):
                get = lambda name: rows[r].get(start + lower.index(name)) if name in lower else None  # noqa: E731
                amount = rows[r].get(start + amount_i)
                when = _date(get("date"))
                item = str(get("item") or "").strip()
                if not isinstance(amount, float) or not amount or (need_date and when is None) or not (item or when):
                    continue
                row = {"date": when.isoformat() if when else "", "item": item, "amount": round(abs(amount), 2),
                       "category": str(get("category") or "").strip(),
                       "importance": str(get("importance") or "").strip(),
                       "remarks": str(get("remarks") or "").strip()}
                if rm_i is not None and isinstance(rows[r].get(start + rm_i), float):
                    row["in_rm"] = rows[r][start + rm_i]
                found.append(row)
            return found

        rm_rows = take(*rm, True)
        seen: Counter = Counter()
        for r in rm_rows:
            r.update(kind="spend", source="", key=_key(f"{title}|spend|{r['date']}|{r['item']}|{r['amount']:.2f}", seen))
        cash: dict[str, list[dict]] = {}
        for s, names, code in cash_blocks:
            cash.setdefault(code, []).extend(take(s, names, False))
        paid = []
        for s, names, _ in paid_blocks:
            paid += take(s, names, False)
        pseen: Counter = Counter()
        for r in paid:
            r["key"] = _key(f"{title}|paid|{r['date']}|{r['item']}|{r['amount']:.2f}", pseen)
        received = []
        for s, names, code in received_blocks:
            received += [dict(r, currency=code) for r in take(s, names, False)]

        start, end, row1_rate, named = row1[title]
        cash_dates = sorted(date.fromisoformat(r["date"]) for rs in cash.values() for r in rs if r["date"])
        rm_dates = sorted(date.fromisoformat(r["date"]) for r in rm_rows if r["date"])
        # Row 1 was sometimes copied from another trip: its dates count when it
        # names this trip, or when they're its own (no other tab has them, same year).
        trusted = start and end and (named or (shared[(start, end)] == 1 and (not years or start.year in years)))
        if not trusted:
            other_dates = sorted(date.fromisoformat(r["date"]) for r in paid + received if r["date"])
            if cash_dates:
                start, end = cash_dates[0], cash_dates[-1]
            elif rm_dates:
                last = rm_dates[-1]
                near = [d for d in rm_dates if (last - d).days <= 14]  # bookings come weeks before
                start, end = near[0], last
            elif other_dates:
                start, end = other_dates[0], other_dates[-1]
            else:
                continue
        if end < start:
            start, end = end, start

        currencies = []
        for n, code in enumerate(cash):
            rate = None
            if n == 0:
                rate = row1_rate or _old_rate(rows, code)
            if rate is None:  # worked out from a block's own RM column
                pairs = [(r["amount"], r["in_rm"]) for r in cash[code] if r.get("in_rm")]
                if pairs and sum(a for a, _ in pairs):
                    rate = round(sum(m for _, m in pairs) / sum(a for a, _ in pairs), 6)
            currencies.append({"code": code, "rate": rate})
        for rs in cash.values():
            for r in rs:
                r.pop("in_rm", None)
        out.append({
            "name": title, "currencies": currencies, "start": start.isoformat(), "end": end.isoformat(),
            "year": _year([start, end], years[0] if years else start.year),
            "rm": rm_rows, "paid": paid, "cash": cash, "received": received,
        })
    return out


def sheets_from_workbook(data: bytes, skip: set[str] = frozenset()) -> list[dict]:
    """Other tabs made of tables under a header row 2 like Date, Person,
    Amount (RM), Remarks (the 2023 "Chinese New Year" ang pao tab). Whether a
    sheet counted as earnings or spending comes from the old Year End
    Summary's formulas."""
    sums: dict[str, set[tuple[int, int]]] = {}
    sheets = read_sheets(data, sums)
    months = month_tabs(sheets)
    years = [parse_month_title(t)[0] for t in months.values()]
    summary = next((t for t in sheets if t.strip().lower() == "year end summary"), None)
    formulas = _formulas(data, summary) if summary else []
    out = []
    for title, rows in sheets.items():
        if title in months or title in skip or title == summary:
            continue
        hr = next((r for r in (1, 2, 3) if r in rows and any(_amount_currency(v) for v in rows[r].values())), None)
        if hr is None or (hr == 3 and "Category" in {str(v).strip() for v in rows[3].values()}):
            continue  # not a table tab (a trip-shaped tab is a trip)
        header = rows[hr]
        tables, all_dates = [], []
        starts = _starts(header) or [min(c for c, v in header.items() if str(v).strip())]  # no Date column
        for start in starts:
            names = _block(header, start)
            amount_i = next((i for i, h in enumerate(names) if _amount_currency(h)), None)
            if amount_i is None or len(names) < 3:
                continue
            label_i = 1 if names[0].lower() == "date" else 0
            label = names[label_i] if amount_i != label_i else "Item"
            remarks_i = next((i for i, h in enumerate(names) if h.lower() == "remarks"), None)
            currency = _amount_currency(names[amount_i]) or "RM"
            heading = rows.get(hr - 1, {}).get(start) if hr > 1 else None
            found, seen = [], Counter()
            for r in sorted(k for k in rows if k > hr):
                cells = rows[r]
                amount = cells.get(start + amount_i)
                has_date = names[0].lower() == "date"
                when = _date(cells.get(start)) if has_date else None
                item_i = 1 if has_date else 0
                item = str(cells.get(start + item_i) or "").strip() if amount_i != item_i else ""
                remarks = str(cells.get(start + remarks_i) or "").strip() if remarks_i is not None else ""
                first = cells.get(start)
                if not isinstance(amount, float) or not amount or (r, start + amount_i) in sums.get(title, set()) \
                        or (isinstance(first, str) and "total" in first.lower()):
                    continue  # blanks, and the old total row (a SUM)
                found.append({"date": when.isoformat() if when else "", "item": item, "amount": round(abs(amount), 2),
                              "remarks": remarks, "key": _key(f"{title}|{start}|{when}|{item}|{amount:.2f}", seen)})
                if when:
                    all_dates.append(when)
            name = f"{heading} ({currency})" if heading else title if len(starts) == 1 else currency
            tables.append({"name": name, "currency": currency, "label": label, "rows": found})
        if not any(t["rows"] for t in tables):
            continue
        counts = ""
        if len(formulas) >= 2:
            refs = (f"'{title}'!", f"{title}!")
            counts = "earnings" if any(x in formulas[0] for x in refs) else \
                "spending" if any(x in formulas[1] for x in refs) else ""
        out.append({"name": title, "year": _year(all_dates, years[0] if years else date.today().year),
                    "counts": counts, "tables": tables})
    return out

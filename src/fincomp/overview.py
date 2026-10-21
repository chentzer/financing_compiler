"""What the app's Home and Trips screens show, read back from the yearly
spreadsheets: a year's totals (and so the to-date totals across years) and
one trip's blocks. Pure: ranges to read in, values in, dicts out."""

from __future__ import annotations

from .accounts import (
    CURRENCY_START, PAID_COLS, SPEND_COLS, TRIP_FIRST_ROW,
    YEAR_SUMMARY, col_letter, col_number, currency_cols, month_title, received_cols, trip_width,
)
from .config import Trip
from .sheetplan import as_amount, as_date, parse_summary, quote, summary_ranges

# ---- a year -------------------------------------------------------------------------


def year_ranges(year: int, titles: list[str]) -> list[str]:
    """Each month tab's summary cells (3 ranges a month), then the Year End
    Summary (which also counts your own sheets, e.g. ang pao)."""
    out = []
    for m in range(1, 13):
        t = month_title(year, m)
        if t in titles:
            out += summary_ranges(t)
    if YEAR_SUMMARY in titles:
        out.append(f"{quote(YEAR_SUMMARY)}!A1:B4")
    return out


def year_totals(year: int, titles: list[str], values: list[list[list]]) -> dict:
    months, cats, imps = [], {}, {}
    i = 0
    for m in range(1, 13):
        if month_title(year, m) not in titles:
            continue
        sm = parse_summary(*values[i:i + 3])
        i += 3
        months.append({"month": m, "earnings": sm["earnings"], "spendings": sm["spendings"],
                       "trips": sm["trips"], "final": sm["final"]})
        for src, out in ((sm["byCategory"], cats), (sm["byImportance"], imps)):
            for k, v in src.items():
                if k != "Total":
                    out[k] = round(out.get(k, 0.0) + v, 2)
    earnings = sum(m["earnings"] for m in months)
    spendings = sum(m["spendings"] for m in months)
    trips = sum(m["trips"] for m in months)
    if YEAR_SUMMARY in titles and i < len(values):
        # B1 earnings, B2 spending incl. trips, B4 trips: your own sheets included.
        b = {str(r[0]): as_amount(r[1]) for r in values[i] if len(r) >= 2}
        earnings = b.get("Total Earnings", earnings)
        trips = b.get("of which Trips", trips)
        spendings = b.get("Total Spending", spendings + trips) - trips
    r2 = lambda x: round(x, 2)  # noqa: E731
    return {"year": year, "months": months, "byCategory": cats, "byImportance": imps,
            "earnings": r2(earnings), "spendings": r2(spendings), "trips": r2(trips),
            "final": r2(earnings - spendings - trips)}


# ---- a trip -------------------------------------------------------------------------


def trip_range(trip: Trip) -> str:
    return f"{quote(trip.name)}!A{TRIP_FIRST_ROW}:{col_letter(max(trip_width(trip), CURRENCY_START) - 1)}"


def _iso(v) -> str:
    d = as_date(v)
    return d.isoformat() if d else ""


def _v(r: list, i: int):
    return r[i] if i < len(r) else ""


def _s(r: list, i: int) -> str:
    return str(r[i]).strip() if i < len(r) and r[i] is not None else ""


def _rate(v, fallback):
    try:
        return float(v)  # not rounded: RM per 1 IDR is 0.00026
    except (TypeError, ValueError):
        return fallback


def trip_detail(trip: Trip, values: list[list]) -> dict:
    """values: the tab from row 4 (trip_range), UNFORMATTED_VALUE."""
    a = col_number(SPEND_COLS[0])
    p = col_number(PAID_COLS[0])
    q = col_number("Q")
    cell = lambda row, col: values[row - TRIP_FIRST_ROW][col] if (  # noqa: E731
        row - TRIP_FIRST_ROW < len(values) and col < len(values[row - TRIP_FIRST_ROW])) else ""

    rm, paid = [], []
    for r in values:
        if _s(r, a + 1) or _s(r, a + 3):
            rm.append({"date": _iso(_v(r, a)), "item": _s(r, a + 1), "category": _s(r, a + 2),
                       "amount": as_amount(_s(r, a + 3)), "importance": _s(r, a + 4),
                       "source": _s(r, a + 5), "remarks": _s(r, a + 6)})
        if _s(r, p + 1) or _s(r, p + 2):
            paid.append({"date": _iso(_v(r, p)), "item": _s(r, p + 1), "amount": as_amount(_s(r, p + 2)),
                         "remarks": _s(r, p + 3)})

    currencies = []
    for i, (code, rate) in enumerate(trip.currencies()):
        c = [col_number(x) for x in currency_cols(i)]
        rows = [{"date": _iso(_v(r, c[0])), "item": _s(r, c[1]), "category": _s(r, c[2]),
                 "amount": as_amount(_s(r, c[3])), "importance": _s(r, c[4]), "remarks": _s(r, c[5])}
                for r in values if _s(r, c[1]) or _s(r, c[3])]
        row = 8 + 4 * i
        sheet_rate = cell(row + 1, q)
        currencies.append({
            "code": code, "rate": _rate(sheet_rate, rate),
            "spent": as_amount(cell(row, q)), "rm": as_amount(cell(row + 2, q)), "rows": rows})

    received = []
    if trip.currencies():
        c = [col_number(x) for x in received_cols(len(trip.currencies()))]
        received = [{"date": _iso(_v(r, c[0])), "item": _s(r, c[1]), "currency": _s(r, c[2]),
                     "amount": as_amount(_s(r, c[3])), "remarks": _s(r, c[4])}
                    for r in values if _s(r, c[1]) or _s(r, c[3])]
    return {
        "name": trip.name, "start": trip.start.isoformat(), "end": trip.end.isoformat(),
        "total": as_amount(cell(4, q)), "spentRm": as_amount(cell(5, q)), "paidBack": as_amount(cell(6, q)),
        "rm": rm, "paid": paid, "currencies": currencies, "received": received,
    }


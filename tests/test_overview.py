"""Home's yearly / to-date totals and the Trips screen. Made-up data only."""

from datetime import date

from fincomp import overview
from fincomp.config import Trip

TITLES = ["To Update", "January 2026", "February 2026", "Bali Trip", "Year End Summary"]


def test_year_totals_from_months_and_year_end_summary():
    ranges = overview.year_ranges(2026, TITLES)
    assert len(ranges) == 7 and ranges[-1] == "'Year End Summary'!A1:B4"
    jan = [[["Food", 100], ["Total", 100]], [["Essential", 100]],
           [["Earnings", 3000], ["Spendings", 100], ["Trips", 0], ["Final", 2900]]]
    feb = [[["Food", 50], ["Bills", 20]], [], [["Earnings", 3000], ["Spendings", 70], ["Trips", 400], ["Final", 2530]]]
    yes = [[["Total Earnings", 6200], ["Total Spending", 570], ["Difference", 5630], ["of which Trips", 400]]]
    out = overview.year_totals(2026, TITLES, jan + feb + yes)
    assert [m["month"] for m in out["months"]] == [1, 2]
    assert out["byCategory"] == {"Food": 150, "Bills": 20}
    # Year End Summary wins: it also counts your own sheets (ang pao: +200).
    assert (out["earnings"], out["spendings"], out["trips"], out["final"]) == (6200, 170, 400, 5630)
    no_yes = overview.year_totals(2026, TITLES[:-1], jan + feb)
    assert (no_yes["earnings"], no_yes["final"]) == (6000, 5430)


def test_trip_detail_blocks():
    trip = Trip("Bali Trip", date(2026, 6, 20), date(2026, 6, 23), currency="IDR", rate=0.00026)
    assert overview.trip_range(trip) == "'Bali Trip'!A4:AE"
    row = [""] * 31
    r4 = list(row)
    r4[0:8] = [46193, "Hotel", "Misc", 340, "Essential", "Maybank", "", "k1"]
    r4[9:13] = [46195, "Bob Lim", 15, ""]
    r4[15:17] = ["Trip Total (RM)", 455]
    r4[18:24] = [46194, "Car Rental", "Transport", 500000, "", ""]
    r4[25:30] = [46193, "Money Exchange", "IDR", 600000, ""]
    r5 = list(row)
    r5[15:17] = ["Spent in RM", 340]
    r6 = list(row)
    r6[15:17] = ["Paid back to you", 15]
    r8, r9, r10 = list(row), list(row), list(row)
    r8[16], r9[16], r10[16] = 500000, 0.00026, 130
    out = overview.trip_detail(trip, [r4, r5, r6, list(row), r8, r9, r10])
    assert (out["total"], out["spentRm"], out["paidBack"]) == (455, 340, 15)
    assert out["rm"][0]["item"] == "Hotel" and out["rm"][0]["date"] == "2026-06-20"
    assert out["paid"] == [{"date": "2026-06-22", "item": "Bob Lim", "amount": 15, "remarks": ""}]
    (idr,) = out["currencies"]
    assert (idr["code"], idr["rate"], idr["spent"], idr["rm"]) == ("IDR", 0.00026, 500000, 130)
    assert [r["item"] for r in idr["rows"]] == ["Car Rental"]
    assert out["received"][0]["currency"] == "IDR"

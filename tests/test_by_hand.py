"""Rows placed by hand in the app: added, or moved to a trip."""

from datetime import date

from fincomp import sheetplan, webapi
from fincomp import settings as S
from fincomp.config import Config, Trip

JAPAN = Trip("Japan Trip", date(2026, 11, 1), date(2026, 11, 9), currency="Yen")
PENANG = Trip("Penang Trip", date(2026, 9, 1), date(2026, 9, 3))


def settings_with(*trips: Trip) -> dict:
    tabs = S.tabs_from_config(Config(trips=list(trips)))
    tabs[S.REMOVED] = [S.HEADERS[S.REMOVED]]
    return tabs


def test_move_a_row_to_a_trip():
    webapi.use_settings(settings_with(JAPAN))
    titles = ["To Update", "November 2026", "Year End Summary"]
    ids = {t: i for i, t in enumerate(titles)}
    month = {"'November 2026'!A3:H": [[46330, "Hotel", "Bills", 300, "", "Card", "AGODA", "k9"]],
             "'November 2026'!P3:U": []}
    taken = webapi.take_row("k9", month, ids)
    assert taken["row"]["item"] == "Hotel" and taken["row"]["date"] == "2026-11-04"
    (remove,) = taken["requests"]
    assert remove["deleteRange"]["range"]["endColumnIndex"] == 8  # Spendings block only

    # Once removed from the month, it goes on the trip (made now, before December).
    prep = webapi.prepare_rows(2026, titles, [taken["row"]], "Japan Trip")
    assert [t["title"] for t in prep["add"]] == ["Japan Trip"]
    titles.insert(prep["add"][0]["index"], "Japan Trip")
    ids["Japan Trip"] = 50
    done = webapi.finish_rows(2026, ids, {r: [] for r in prep["reads"]})
    data = {d["range"]: d["values"] for d in done["data"]}
    assert data["'Japan Trip'!A4:H4"][0][:2] == ["2026-11-04", "Hotel"] and data["'Japan Trip'!A4:H4"][0][7] == "k9"
    assert data["'November 2026'!X5"] == [["='Japan Trip'!Q4"]]  # the trip comes off November's Final
    assert not any(r.startswith("'To Update'") for r in data)  # cards left alone
    assert done["added"] == 1


def test_add_a_row_by_hand_makes_its_month_tab():
    webapi.use_settings(settings_with())
    titles = ["To Update", "September 2026", "Year End Summary"]
    row = {"kind": "earn", "date": "2026-10-02", "item": "Angpow", "amount": 88, "source": "Cash",
           "remarks": "from grandma", "key": "m-abc123"}
    assert webapi.place_target("", row["date"]) == {"title": "October 2026", "trip": False, "year": 2026,
                                                     "currencies": []}
    prep = webapi.prepare_rows(2026, titles, [row], "October 2026")
    assert [(t["title"], t["index"]) for t in prep["add"]] == [("October 2026", 2)]
    ids = {t: i for i, t in enumerate(titles + ["October 2026"])}
    done = webapi.finish_rows(2026, ids, {r: [] for r in prep["reads"]})
    data = {d["range"]: d["values"] for d in done["data"]}
    assert data["'October 2026'!P3:U3"] == [["2026-10-02", "Angpow", 88.0, "Cash", "from grandma", "m-abc123"]]
    assert data["'October 2026'!X6"] == [["='September 2026'!X6+X3-X4-X5"]]


def test_trip_cash_in_its_currency_and_rate_refresh():
    webapi.use_settings(settings_with(Trip("Japan Trip", date(2026, 11, 1), date(2026, 11, 9), currency="Yen",
                                           rate=0.031)))
    (w,) = webapi.cash_row([["x"], ["y"]], "Japan Trip", {"date": "2026-11-03", "item": "Ramen", "amount": 1200,
                                                          "category": "Food"}, "yen")
    assert w == {"range": "'Japan Trip'!S6:X6", "values": [["2026-11-03", "Ramen", "Food", 1200, "", ""]]}
    (p,) = webapi.paid_row([], "Japan Trip", {"date": "2026-11-10", "item": "Bob", "amount": 45, "key": "m-1"})
    assert p == {"range": "'Japan Trip'!J4:N4", "values": [["2026-11-10", "Bob", 45.0, "", "m-1"]]}
    out = webapi.trip_refresh({"Japan Trip": 4, "Other": 5})
    cells = {d["range"]: d["values"][0][0] for d in out["data"]}
    assert cells["'Japan Trip'!Q9"] == 0.031 and cells["'Japan Trip'!X3"] == "Remarks"
    assert all(r[next(iter(r))].get("range", {}).get("sheetId", 4) == 4 for r in out["requests"])


def test_move_adds_first_and_is_safe_to_retry():
    webapi.use_settings(settings_with(JAPAN))
    titles = ["To Update", "November 2026", "Japan Trip", "Year End Summary"]
    ids = {t: i for i, t in enumerate(titles)}
    # Still on the month: a move puts it on the trip anyway, and says where it came from.
    month = {"'November 2026'!A3:H": [[46330, "Hotel", "Bills", 300, "", "Card", "AGODA", "k9"]]}
    row = webapi.take_row("k9", month, ids)["row"]
    assert row["tab"] == "November 2026"
    prep = webapi.prepare_rows(2026, titles, [row], "Japan Trip")
    reads = {r: [] for r in prep["reads"]} | month
    assert webapi.finish_rows(2026, ids, reads, True)["added"] == 1
    assert webapi.finish_rows(2026, ids, reads)["added"] == 0  # a normal placing would skip it
    # Tried again after the first try got that far: it isn't put there twice.
    reads["'Japan Trip'!A4:H"] = [[46330, "Hotel", "Bills", 300, "", "Card", "AGODA", "k9"]]
    assert webapi.finish_rows(2026, ids, reads, True)["added"] == 0


def test_money_in_moves_to_a_trip_as_paid_back_and_stays_there():
    webapi.use_settings(settings_with(JAPAN))
    titles = ["To Update", "November 2026", "Japan Trip", "Year End Summary"]
    ids = {t: i for i, t in enumerate(titles)}
    month = {"'November 2026'!P3:U": [[46335, "Flight + Accoms", 1374.47, "Ryt Bank", "From Bob", "k5"]]}
    row = webapi.take_row("k5", month, ids)["row"]
    prep = webapi.prepare_rows(2026, titles, [row], "Japan Trip")
    assert "'Japan Trip'!J4:N" in prep["reads"]
    done = webapi.finish_rows(2026, ids, {r: [] for r in prep["reads"]} | month, True)
    data = {d["range"]: d["values"] for d in done["data"]}
    assert data["'Japan Trip'!J4:N4"] == [["2026-11-09", "Flight + Accoms", 1374.47, "From Bob", "k5"]]
    # Once there, it's found by its key: an upload won't add it back to November, and it moves back.
    paid = {"'Japan Trip'!J4:N": [[46335, "Flight + Accoms", 1374.47, "From Bob", "k5"]]}
    back = webapi.take_row("k5", paid, ids)
    assert back["row"]["kind"] == "earn" and back["row"]["remarks"] == "From Bob"
    assert back["requests"][0]["deleteRange"]["range"]["startColumnIndex"] == 9  # J-N only
    assert webapi.row_sources(paid) == {"k5": ""}
    (found,) = webapi.all_rows(paid)
    assert (found["kind"], found["trip"], found["amount"]) == ("earn", "Japan Trip", 1374.47)


def test_a_formula_amount_moves_with_its_value():
    webapi.use_settings(settings_with(JAPAN))
    # Read with UNFORMATTED_VALUE, so =150/3 arrives as 50.
    values = {"'November 2026'!A3:H": [[46330, "Dinner split", "Food", 50, "", "", "", "k1"]]}
    assert webapi.take_row("k1", values, {"November 2026": 1})["row"]["amount"] == 50.0


def test_date_typed_in_sheets_reads_as_a_date():
    tabs = {S.TRIPS: [S.HEADERS[S.TRIPS], ["Japan", 46327, 46335, "", "", "", "", ""],
                      ["Broken", "next week", "2026-01-02", "", "", "", "", ""]]}
    (trip,) = S.config_from_tabs(tabs).trips  # the unreadable one is left out, not a crash
    assert (trip.start, trip.end) == (date(2026, 11, 1), date(2026, 11, 9))


def test_deleting_a_trip_sends_its_rm_rows_to_their_months():
    webapi.use_settings(settings_with(JAPAN))
    assert webapi.trip_leave_ranges("Japan Trip")[:2] == ["'Japan Trip'!A4:H", "'Japan Trip'!J4:N"]
    values = [
        [[46330, "Hotel", "Bills", 300, "", "Card", "AGODA", "k1"], [46331, "Cash lunch", "Food", 20, "", "", "", ""],
         ["", "No date", "", 5, "", "", "", ""]],
        [[46332, "Bob", 45, "payback", "m-1"]],
        [[46331, "Ramen", "Food", 1200, "", ""]],  # yen: no month to go to
        [],
    ]
    out = webapi.trip_leaving("Japan Trip", values)
    assert out["left"] == 2
    spend, typed, paid = out["rows"]
    assert (spend["kind"], spend["date"], spend["key"]) == ("spend", "2026-11-04", "k1")
    assert typed["key"].startswith("m-") and typed["key"] == webapi.trip_leaving("Japan Trip", values)["rows"][1]["key"]
    assert (paid["kind"], paid["item"], paid["amount"], paid["key"]) == ("earn", "Bob", 45.0, "m-1")

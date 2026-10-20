"""Converting old tabs to the Source / gap-column layout, and rows placed by
hand in the app: added, or moved to a trip."""

from datetime import date

from fincomp import sheetplan, webapi
from fincomp import settings as S
from fincomp.accounts import AccountRow
from fincomp.config import Config, Trip

JAPAN = Trip("Japan Trip", date(2026, 11, 1), date(2026, 11, 9), currency="Yen")
PENANG = Trip("Penang Trip", date(2026, 9, 1), date(2026, 9, 3))


def test_old_tabs_are_found_and_get_columns_inserted_right_to_left():
    headers = {
        "'September 2026'!A2:H2": [["Date", "Item", "Category", "Amount (RM)", "Importance", "Remarks", "Key"]],
        "'October 2026'!A2:H2": [["Date", "Item", "Category", "Amount (RM)", "Importance", "Source", "Remarks", "Key"]],
        "'Japan Trip'!A3:H3": [["Date", "Item", "Category", "Amount (RM)", "Importance", "Remarks", "Key"]],
    }
    old = sheetplan.old_tabs(headers)
    assert old == ["September 2026"]  # trip tabs are rebuilt instead (trip_versions)
    # Inserted but cut short before the headers were rewritten: only finished, never inserted again.
    half = {"'May 2026'!A2:H2": [["Date", "Item", "Category", "Amount (RM)", "Importance", "", "Remarks", "Key"]]}
    assert sheetplan.old_tabs(half) == [] and sheetplan.unfinished_tabs(half) == ["May 2026"]
    reqs = sheetplan.insert_columns({"September 2026": 1, "Japan Trip": 2}, old)
    starts = [(r["insertDimension"]["range"]["sheetId"], r["insertDimension"]["range"]["startIndex"]) for r in reqs]
    assert starts == [(1, 18), (1, 16), (1, 7), (1, 5)]
    trips = {
        "'Japan Trip'!A3:Z3": [["Date", "Item", "Category", "Amount (RM)", "Importance", "Remarks", "Key"]],
        "'Bali Trip'!A3:Z3": [["Date", "Item", "Category", "Amount (RM)", "Importance", "Source", "Remarks", "Key"]],
        "'Cebu Trip'!A3:Z3": [["Date", "Item", "Category", "Amount (RM)", "Importance", "Source", "Remarks", "Key", "",
                               "Date", "From", "Amount (RM)", "Remarks", "Key", "", "Summary"]],
    }
    assert sheetplan.trip_versions(trips) == {"Japan Trip": "v1", "Bali Trip": "v2"}  # Cebu is current


def test_old_trip_tab_rebuilt_with_its_rows():
    trip = Trip("Japan Trip", date(2026, 11, 1), date(2026, 11, 9), currency="JPY", rate=0.03)
    config = Config(trips=[trip])
    v2_rows = [  # A-G RM + key H, J-O yen spending, T-W yen received
        [46330, "Hotel", "Bills", 300, "", "Card", "AGODA", "k1", "", 46331, "Ramen", "Food", 1200, "", "", "", "", "",
         "", 46320, "Money Exchange", 10000, ""],
        ["", "", "", "", "", "", "", "", "", 46332, "Train", "Transport", 800, "", "", "", "", "", "", "", "", "", ""],
    ]
    clear, data, requests = sheetplan.trip_rebuild(trip, "v2", v2_rows, {}, config, 7)
    cells = {d["range"]: d["values"] for d in data}
    assert clear == ["'Japan Trip'!A1:AE1000"]
    assert cells["'Japan Trip'!A4:H4"] == [[46330, "Hotel", "Bills", 300, "", "Card", "AGODA", "k1"]]
    assert cells["'Japan Trip'!S4:X5"][1][:4] == [46332, "Train", "Transport", 800]
    assert cells["'Japan Trip'!Z4:AD4"] == [[46320, "Money Exchange", "JPY", 10000, ""]]
    assert cells["'Japan Trip'!Q4"] == [["=Q5-Q6+Q10"]]
    assert any("hiddenByUser" in str(r) for r in requests)


def test_upgrade_fills_source_and_swaps_automatic_remarks_only():
    config = Config()
    rows = [
        AccountRow("spend", date(2026, 9, 5), "Lunch", 16.4, "BOB LIM - DuitNowID - lunch", "k1", who="To Bob",
                   source="AEON Bank"),
        AccountRow("spend", date(2026, 9, 6), "SHOPEE MY", 63.6, "SHOPEE MY", "k2", who="SHOPEE MY", source="Card"),
        AccountRow("spend", date(2026, 9, 7), "Dinner", 40, "BOB LIM - DuitNow", "k3", who="To Bob", source="TNG"),
        AccountRow("earn", date(2026, 9, 16), "Payback", 107, "AMY WONG - DuitNowQR", "k4", who="From Amy",
                   source="TNG"),
    ]
    # As read after the inserts: Source (F / S) empty, Remarks (G / T) as fincomp or you left them.
    values = {
        "'September 2026'!A3:H": [
            [46270, "Lunch", "Food", 16.4, "", "", "To Bob", "k1"],
            [46271, "SHOPEE MY", "Shopping", 63.6, "", "", "Card", "k2"],
            [46272, "Dinner", "Food", 40, "", "", "birthday treat", "k3"],  # your own note stays
            [46273, "Cash", "Food", 6, "", "", "", ""],  # typed by hand: untouched
        ],
        "'September 2026'!P3:U": [[46281, "Payback", 107, "", "From Amy", "k4"]],
    }
    clear, data, requests = sheetplan.upgrade_finish({"September 2026": 5}, ["September 2026"], values, rows, config)
    cells = {d["range"]: d["values"][0][0] for d in data}
    assert cells["'September 2026'!F3"] == "AEON Bank" and cells["'September 2026'!G3"] == "BOB LIM - DuitNowID - lunch"
    assert cells["'September 2026'!F4"] == "Card" and cells["'September 2026'!G4"] == "SHOPEE MY"
    assert cells["'September 2026'!F5"] == "TNG" and "'September 2026'!G5" not in cells
    assert "'September 2026'!F6" not in cells
    assert cells["'September 2026'!S3"] == "TNG" and cells["'September 2026'!T3"] == "AMY WONG - DuitNowQR"
    # New headers and summaries, the old summary area cleared first.
    assert cells["'September 2026'!G2"] == "Remarks" and cells["'September 2026'!W6"] == "Final"
    assert clear == ["'September 2026'!J3:N40"]
    hidden = [r["updateDimensionProperties"]["range"]["startIndex"] for r in requests
              if r.get("updateDimensionProperties", {}).get("properties", {}).get("hiddenByUser")]
    assert hidden == [7, 20]  # H and U: the keys


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

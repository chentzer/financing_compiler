"""The app's flow through webapi.py, with a stand-in for the JavaScript side
that executes the plans against an in-memory spreadsheet."""

from datetime import date

import pytest

from fincomp import pipeline, settings as S, webapi
from fincomp.config import Config, Trip
from fincomp.models import Transaction
from fincomp.parsers.base import Parser


def tx(day, amount, desc, who="", purpose="", source="Bank A", **kw):
    return Transaction(date=date(2026, 9, day), source=source, account="acc", description=desc,
                       amount=amount, counterparty=who, purpose=purpose, **kw)


class FakeParser(Parser):
    name = "fake"
    label = "Bank A"
    default_patterns = ["*.pdf"]
    rows: list = []

    def parse_bytes(self, name, data, password=""):
        return [Transaction(**{**vars(t), "file": name}) for t in self.rows]


@pytest.fixture(autouse=True)
def fake_parser(monkeypatch):
    FakeParser.rows = [
        tx(5, -16.40, "BOB LIM - DuitNowID - lunch", who="BOB LIM", purpose="lunch"),
        tx(16, 107.00, "AMY WONG - DuitNowQR - DuitNow QR", who="AMY WONG", type="DuitNowQR"),
        tx(20, -63.60, "SHOPEE MY", source="Card"),
        tx(21, -500.0, "JANE TAN", who="JANE TAN", internal=True, transfer=True),
    ]
    monkeypatch.setattr(pipeline, "build_parsers", lambda config: [FakeParser(config)])


def settings_values():
    cfg = Config(rules=[{"match": "SHOPEE", "category": "Shopping"}], people={"BOB LIM": "Bob"})
    tabs = S.tabs_from_config(cfg)
    tabs[S.REMOVED] = [S.HEADERS[S.REMOVED]]
    return tabs


class Sheet:
    """Just enough of a spreadsheet: tab titles/ids and cell values."""

    def __init__(self, titles):
        self.titles = list(titles)
        self.ids = {t: i for i, t in enumerate(titles)}
        self.cells: dict[str, list] = {}  # "'Tab'!A3:G7" -> rows, as written
        self.requests: list[dict] = []

    def run(self, plan):
        for t in plan["add"]:
            self.titles.insert(t["index"], t["title"])
            self.ids[t["title"]] = 100 + len(self.ids)
        for t in plan["delete"]:
            self.titles.remove(t)


def upload(sheet: Sheet, values: dict, created=False):
    out = webapi.compile_upload([{"name": "sep.pdf", "data": b"x"}], settings_values(), {}, [])
    (year,) = out["years"]
    prep = webapi.prepare_year(year, sheet.titles, created)
    sheet.run(prep)
    done = webapi.finish_year(year, {t: sheet.ids[t] for t in sheet.titles}, {r: values.get(r, []) for r in prep["reads"]})
    return out, prep, done


def test_upload_compiles_and_plans_the_year():
    sheet = Sheet(["Sheet1"])
    out, prep, done = upload(sheet, {}, created=True)

    assert out["files"][0]["ok"] and out["files"][0]["count"] == 4
    assert out["toUpdate"] == 2  # Amy (what for) and lunch (Category)
    assert sheet.titles == ["To Update", "September 2026", "Year End Summary"]
    data = {d["range"]: d["values"] for d in done["data"]}
    spend = data["'September 2026'!A3:H4"]
    assert [r[1] for r in spend] == ["Lunch", "SHOPEE MY"] and spend[0][5] == "Bank A"  # Source
    assert data["'September 2026'!P3:U3"][0][1] == "QR payment"
    assert done["added"] == 3 and done["toUpdate"] == 2
    # The Ledger keeps every parsed row, internal ones too, for later uploads.
    ledger = S.ledger_from_rows(out["ledger"])
    assert len(ledger) == 4 and ledger[3].internal


def test_cards_edit_and_not_mine():
    to_update = [
        ["2026-09-05", -16.4, "To Bob", "BOB LIM - DuitNowID - lunch", "Lunch", "Category", "September 2026", "k1"],
        [46281, 107.0, "From Amy Wong", "AMY WONG - DuitNowQR", "QR payment", "what it was for", "September 2026", "k2"],
    ]
    cards = webapi.cards(to_update)
    assert [(c["row"], c["needsPurpose"], c["needsCategory"], c["key"]) for c in cards] == [
        (2, False, True, "k1"), (3, True, False, "k2"),
    ]
    assert cards[1]["date"] == "2026-09-16"  # Sheets date serial -> ISO

    month = {
        "'September 2026'!A3:H": [["2026-09-05", "Lunch", "", 16.4, "", "Bank A", "", "k1"]],
        "'September 2026'!P3:U": [["2026-09-16", "QR payment", 107.0, "Bank A", "", "k2"]],
    }
    ids = {"September 2026": 7, "To Update": 9}
    edit = webapi.edit_row("k1", month, ids, {"category": "Food", "importance": "Essential"})
    assert edit["data"] == [
        {"range": "'September 2026'!C3", "values": [["Food"]]},
        {"range": "'September 2026'!E3", "values": [["Essential"]]},
    ]
    gone = webapi.remove_row("k2", month, ids, cards[1])
    (req,) = gone["requests"]
    assert req["deleteRange"]["range"] == {
        "sheetId": 7, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 15, "endColumnIndex": 21,
    }
    assert gone["removed"][0] == "k2"
    assert webapi.remove_card(9, 3)["deleteDimension"]["range"]["startIndex"] == 2


def test_removed_rows_stay_out_on_the_next_upload():
    first = webapi.compile_upload([{"name": "sep.pdf", "data": b"x"}], settings_values(), {}, [])
    amy_key = next(r.key for r in webapi._state["compiled"].rows if r.counterparty == "AMY WONG")
    tabs = settings_values()
    tabs[S.REMOVED].append(S.removed_row(amy_key, "2026-09-16", 107.0, "AMY WONG"))
    again = webapi.compile_upload([], tabs, {}, first["ledger"])  # from the Ledger alone
    assert amy_key not in {r.key for r in webapi._state["compiled"].rows}
    assert again["toUpdate"] == 1


def test_summary_and_rows_from_the_sheet():
    s = webapi.month_summary(
        [["Bills", 0], ["Food", 16.4], ["Not set", 0], ["Total", 16.4]],
        [["Essential", 16.4], ["Total", 16.4]],
        [["Earnings", 107], ["Spendings", 16.4], ["Trips", 0], ["Final", 90.6]],
    )
    assert (s["byCategory"]["Food"], s["final"], s["earnings"]) == (16.4, 90.6, 107)
    rows = webapi.month_rows([[46270, "Lunch", "Food", 16.4, "Essential", "TNG", "dinner w Bob", "k1"],
                              ["", "", "", "", "", "", "", ""], [46271, "Cash: nasi lemak", "Food", 6, "", "", "", ""]], [])
    assert [(r["date"], r["item"], r["row"], r["key"]) for r in rows] == [
        ("2026-09-05", "Lunch", 3, "k1"), ("2026-09-06", "Cash: nasi lemak", 5, ""),  # typed by hand: no key
    ]


def test_settings_round_trip():
    cfg = Config(
        rules=[{"match": ["GRAB", "MY50"], "category": "Transport", "importance": "Essential"},
               {"match": "IGNORE", "skip": True}],
        people={"TAN MEI LING": "Mei Ling"},
        trips=[Trip("Japan Trip", date(2026, 11, 8), date(2026, 11, 20), currency="Yen", match=["AIRASIA"])],
        own_payees=["AEON CREDIT SERVICE"],
    )
    back = S.config_from_tabs(S.tabs_from_config(cfg), passwords={"tng": "pw"})
    assert back.rules == cfg.rules and back.people == cfg.people and back.own_payees == cfg.own_payees
    assert back.trips == cfg.trips and back.password("tng") == "pw"
    assert back.categories == cfg.categories


def test_ledger_round_trip_keeps_text():
    t = tx(3, -9.5, "+6012 TOPUP = promo", note="x", file="a.pdf", internal=True)
    (back,) = S.ledger_from_rows(S.ledger_rows([t]))
    assert back == t and back.file == "a.pdf"

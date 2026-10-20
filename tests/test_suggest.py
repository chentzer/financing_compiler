from datetime import date

from fincomp import sheetplan, webapi
from fincomp.config import DEFAULT_CATEGORIES, Config, Trip
from fincomp.suggest import suggest_categories

CATS = list(DEFAULT_CATEGORIES)


def test_shop_words():
    assert suggest_categories("QR Payment KEDAI MAKAN AH SENG", "To Kedai Makan Ah Seng", "QR payment", [], CATS)[0] == "Food"
    assert suggest_categories("PETRONAS SS2", "", "Petronas", [], CATS)[0] == "Transport"
    assert suggest_categories("KLINIK SEJAHTERA", "", "", [], CATS)[0] == "Health"


def test_your_history_beats_shop_words():
    history = [["Badminton", "To Bob Lim", "Entertainment"], ["Lunch", "To Jane Tan", "Food"]]
    # Same person you paid before, nothing else known.
    assert suggest_categories("DuitNow BOB LIM", "To Bob Lim", "Transfer", history, CATS)[0] == "Entertainment"
    # What you typed matches an earlier Item.
    assert suggest_categories("DuitNow BOB LIM", "To Bob Lim", "Lunch", history, CATS)[0] == "Food"


def test_only_your_categories_and_your_own_names():
    mine = ["Food", "Pets"]
    assert suggest_categories("PETRONAS", "", "", [], mine) == []
    assert suggest_categories("PET WORLD", "", "Pets food", [], mine)[:2] == ["Pets", "Food"] or \
        set(suggest_categories("PET WORLD", "", "Pets food", [], mine)) == {"Pets", "Food"}
    # A category that's no longer in the list isn't suggested from history.
    assert suggest_categories("X", "To Bob Lim", "", [["", "To Bob Lim", "Bills"]], mine) == []


def test_new_category_saved_in_lists_and_refreshed_in_tabs():
    settings = {"Lists": [["Categories", "Importance"], ["Food", "Essential"], ["Misc", ""]]}
    rows = webapi.lists_rows(["Food", "Misc", "Pets", "Pets", " "], settings)
    assert rows == [["Food", "Essential"], ["Misc", ""], ["Pets", ""]]
    assert webapi.categories({"Lists": [["Categories", "Importance"], *rows]}) == ["Food", "Misc", "Pets"]

    config = Config(categories=["Food", "Misc", "Pets"], trips=[Trip(
        name="Japan Trip", start=date(2026, 9, 1), end=date(2026, 9, 9), currency="Yen", rate=0.03)])
    plan = sheetplan.category_refresh({"September 2026": 5, "Japan Trip": 7, "Chinese New Year": 9}, 2026, config)
    assert plan["clear"] == ["'September 2026'!J3:K40"]
    cells = {d["range"]: d["values"][0][0] for d in plan["data"]}
    assert cells["'September 2026'!J5"] == "Pets"
    assert cells["'September 2026'!K5"].startswith('=SUMIF(') and '"Pets"' in cells["'September 2026'!K5"]
    assert cells["'September 2026'!J6"] == "Not set"
    assert all(d["range"].split("!")[1][0] in "JK" for d in plan["data"])  # nothing else touched
    sheets = [r["setDataValidation"]["range"]["sheetId"] for r in plan["requests"]]
    assert sorted(sheets) == [5, 7, 7]  # month C; trip C and J; never the user's own tab

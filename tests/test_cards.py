from datetime import date
from pathlib import Path

import openpyxl
import pytest

from fincomp import gsheets
from fincomp.accounts import TO_UPDATE, build_rows, needs_update, plan
from fincomp.accounts_xlsx import write_accounts_xlsx
from fincomp.config import Config
from fincomp.models import Transaction
from fincomp.review import card, load_answers, update_cards
from test_accounts import FakeClient, FakeSheet, writes  # noqa: F401  (fixture helpers)


def tx(d, amount, desc, who="", purpose="", source="AEON Bank"):
    kind = desc.split(" - ")[1] if " - " in desc else ""  # e.g. "DuitNowQR", as the AEON parser sets it
    return Transaction(date=date(2026, 9, d), source=source, account="Savings", description=desc,
                       amount=amount, type=kind, counterparty=who, purpose=purpose)


def sample():
    return [
        tx(5, -16.40, "TAN MEI LING - DuitNowID - lunch", who="TAN MEI LING", purpose="lunch"),  # needs Category
        tx(16, 107.00, "LEE SIEW WEN - DuitNowQR - DuitNow QR", who="LEE SIEW WEN"),  # needs what for
        tx(16, -742.40, "MO-MO PARADISE", source="AEON Credit"),  # needs Category
        tx(20, -63.60, "Shopee MY Marketplace", source="AEON Credit"),  # a rule covers it
        tx(26, -17.00, "AHMAD FAIZ - DuitNowQR - QR Payment", who="AHMAD FAIZ"),  # needs both
    ]


def cfg(tmp_path, **kw):
    return Config(answers=tmp_path / "answers.json", rules=[{"match": "SHOPEE", "category": "Shopping"}], **kw)


def script(*replies):
    it = iter(replies)
    return lambda _prompt: next(it)


def test_every_row_is_recorded_and_knows_what_it_needs(tmp_path):
    rows = build_rows(sample(), cfg(tmp_path))
    assert [(r.item, r.needs) for r in rows] == [
        ("Lunch", ("category",)),
        ("QR payment", ("purpose",)),
        ("MO-MO PARADISE", ("category",)),
        ("Shopee MY Marketplace", ()),
        ("QR payment", ("purpose", "category")),
    ]


def test_card_shows_what_you_need_to_decide(tmp_path):
    row = needs_update(build_rows(sample(), cfg(tmp_path)))[1]
    text = card(row, 2, 4)
    assert "2 of 4" in text and "needs: what it was for" in text
    assert "16 Sep 2026   +RM 107.00   AEON Bank" in text
    assert "From Siew Wen" in text and "Statement: LEE SIEW WEN - DuitNowQR - DuitNow QR" in text
    assert "Recorded as: QR payment" in text


def test_answer_later_and_not_mine(tmp_path):
    c = cfg(tmp_path)
    answers = {}
    todo = needs_update(build_rows(sample(), c))
    update_cards(todo, c, answers, say=lambda _: None, ask=script(
        "food", "1", "n",          # Lunch: Category Food, Importance Essential, don't remember
        "Mo-Mo payback", "",       # Siew Wen: what for, don't remember
        "",                        # Mo-Mo: later
        "s",                       # Ahmad Faiz: not mine
    ))
    saved = load_answers(c.answers)  # saved after every card
    assert len(saved) == 3 and all(a["reviewed"] and not a["synced"] for a in saved.values())

    rows = build_rows(sample(), c, saved)
    assert [(r.item, r.category, r.importance, r.needs) for r in rows] == [
        ("Lunch", "Food", "Essential", ()),
        ("Mo-Mo payback", "", "", ()),
        ("MO-MO PARADISE", "", "", ("category",)),  # left for later: still a card
        ("Shopee MY Marketplace", "Shopping", "", ()),
    ]  # Ahmad Faiz is gone


def test_q_stops_and_keeps_what_you_did(tmp_path):
    c = cfg(tmp_path)
    answers = {}
    todo = needs_update(build_rows(sample(), c))
    assert update_cards(todo, c, answers, say=lambda _: None, ask=script("bills", "", "n", "q")) == 1
    assert len(needs_update(build_rows(sample(), c, load_answers(c.answers)))) == 3


def test_remember_a_regular(tmp_path):
    c = cfg(tmp_path)
    answers = {}
    mo_mo = [r for r in needs_update(build_rows(sample(), c)) if r.item == "MO-MO PARADISE"]
    update_cards(mo_mo, c, answers, say=lambda _: None, ask=script("food", "nice", "y"))
    assert answers["_rules"] == [{"match": "MO-MO PARADISE", "category": "Food", "importance": "Nice to Have"}]
    later = [tx(30, -50.00, "MO-MO PARADISE", source="AEON Credit")]
    (row,) = build_rows(later, c, answers)
    assert (row.category, row.needs) == ("Food", ())


def test_local_workbook_has_to_update_tab(tmp_path):
    c = cfg(tmp_path)
    (path,) = write_accounts_xlsx(tmp_path, plan(build_rows(sample(), c), c), c)
    ws = openpyxl.load_workbook(path)[TO_UPDATE]
    rows = [[cell.value for cell in r] for r in ws.iter_rows(min_row=2)]
    assert [(r[2], r[4], r[5], r[6]) for r in rows] == [
        ("To Mei Ling", "Lunch", "Category", "September 2026"),
        ("From Siew Wen", "QR payment", "what it was for", "September 2026"),
        ("AEON Credit", "MO-MO PARADISE", "Category", "September 2026"),
        ("To Ahmad Faiz", "QR payment", "what it was for, Category", "September 2026"),
    ]


# ---- Google Sheets --------------------------------------------------------


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gsheets, "connect", lambda g: client)
    return client


def test_answers_reach_rows_already_in_the_sheet(fake, tmp_path):
    c = cfg(tmp_path)
    rows = build_rows(sample(), c)
    gsheets.upload(plan(rows, c), c, {})
    sheet = fake.sheets["2026 Accounts"]
    spend = [r for r in rows if r.kind == "spend"]
    earn = [r for r in rows if r.kind == "earn"]
    # The sheet as uploaded (rows 3..), and you then fixed Mo-Mo's Category yourself.
    sheet.values["'September 2026'!A3:G"] = [
        [46000, r.item, "Food" if r.item == "MO-MO PARADISE" else r.category, r.amount, "", r.remarks, r.key]
        for r in spend
    ]
    sheet.values["'September 2026'!N3:R"] = [[46000, r.item, r.amount, r.remarks, r.key] for r in earn]

    answers = {}
    update_cards(needs_update(rows), c, answers, say=lambda _: None, ask=script(
        "food", "1", "n",         # Lunch
        "Mo-Mo payback", "",      # Siew Wen
        "",                       # Mo-Mo: later (already fixed in the sheet, though)
        "s",                      # Ahmad Faiz: not mine
    ))
    (result,) = gsheets.upload(plan(build_rows(sample(), c, answers), c), c, answers)

    w = writes(sheet)
    lunch_row = 3 + [r.item for r in spend].index("Lunch")
    assert w[f"'September 2026'!C{lunch_row}"] == [["Food"]]
    assert w[f"'September 2026'!E{lunch_row}"] == [["Essential"]]
    assert w["'September 2026'!O3"] == [["Mo-Mo payback"]]
    assert f"'September 2026'!B{lunch_row}" not in w  # only the cells you answered
    # Ahmad Faiz's row is removed from the Spendings block only.
    (removal,) = [r["deleteRange"] for r in sheet.requests if "deleteRange" in r]
    abdul_row = 3 + [r.statement for r in spend].index("AHMAD FAIZ - DuitNowQR - QR Payment")
    assert removal["range"]["startRowIndex"] == abdul_row - 1 and removal["range"]["endColumnIndex"] == 7
    assert removal["shiftDimension"] == "ROWS"

    # Mo-Mo was fixed in the sheet, so no card is left.
    assert (result.to_update, result.fixed_in_sheet) == (0, 1)
    assert w["'To Update'!A1:H2"][1][0] == "Nothing to update."
    assert all(a["synced"] for k, a in answers.items() if not a.get("skip"))


def test_to_update_tab_lists_open_cards(fake, tmp_path):
    c = cfg(tmp_path)
    (result,) = gsheets.upload(plan(build_rows(sample(), c), c), c, {})
    sheet = fake.sheets["2026 Accounts"]
    assert sheet.tabs[0].title == TO_UPDATE
    table = writes(sheet)["'To Update'!A1:H5"]
    assert table[0][:6] == ["Date", "Amount (RM)", "Who / where", "Statement", "Recorded as", "Needs"]
    assert [row[5] for row in table[1:]] == ["Category", "what it was for", "Category", "what it was for, Category"]
    assert result.to_update == 4

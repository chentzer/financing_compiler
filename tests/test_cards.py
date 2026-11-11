from datetime import date

from fincomp.accounts import TO_UPDATE, build_rows, plan
from fincomp.config import Config
from fincomp.models import Transaction
from test_accounts import fake, writes  # noqa: F401  (fixture helpers)


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


def cfg(**kw):
    return Config(rules=[{"match": "SHOPEE", "category": "Shopping"}], **kw)


def test_every_row_is_recorded_and_knows_what_it_needs():
    rows = build_rows(sample(), cfg())
    assert [(r.item, r.needs) for r in rows] == [
        ("Lunch", ("category",)),
        ("QR payment", ("purpose",)),
        ("MO-MO PARADISE", ("category",)),
        ("Shopee MY Marketplace", ()),
        ("QR payment", ("purpose", "category")),
    ]


def test_answers_reach_rows_already_in_the_sheet(fake):  # noqa: F811
    c = cfg()
    rows = build_rows(sample(), c)
    fake.upload(plan(rows, c), c, {})
    sheet = fake.sheets["2026 Accounts"]
    spend = [r for r in rows if r.kind == "spend"]
    earn = [r for r in rows if r.kind == "earn"]
    # The sheet as uploaded (rows 3..), and you then fixed Mo-Mo's Category yourself.
    sheet.values["'September 2026'!A3:H"] = [
        [46000, r.item, "Food" if r.item == "MO-MO PARADISE" else r.category, r.amount, "", r.source, r.remarks,
         r.key]
        for r in spend
    ]
    sheet.values["'September 2026'!P3:U"] = [[46000, r.item, r.amount, r.source, r.remarks, r.key] for r in earn]

    key = {r.statement: r.key for r in rows}
    answers = {
        key["TAN MEI LING - DuitNowID - lunch"]: {"category": "Food", "importance": "Essential"},
        key["LEE SIEW WEN - DuitNowQR - DuitNow QR"]: {"item": "Mo-Mo payback"},
        key["AHMAD FAIZ - DuitNowQR - QR Payment"]: {"skip": True},  # not mine
    }
    (result,) = fake.upload(plan(build_rows(sample(), c, answers), c), c, answers)

    w = writes(sheet)
    lunch_row = 3 + [r.item for r in spend].index("Lunch")
    assert w[f"'September 2026'!C{lunch_row}"] == [["Food"]]
    assert w[f"'September 2026'!E{lunch_row}"] == [["Essential"]]
    assert w["'September 2026'!Q3"] == [["Mo-Mo payback"]]
    assert f"'September 2026'!B{lunch_row}" not in w  # only the cells you answered
    # Ahmad Faiz's row is removed from the Spendings block only.
    (removal,) = [r["deleteRange"] for r in sheet.requests if "deleteRange" in r]
    abdul_row = 3 + [r.statement for r in spend].index("AHMAD FAIZ - DuitNowQR - QR Payment")
    assert removal["range"]["startRowIndex"] == abdul_row - 1 and removal["range"]["endColumnIndex"] == 8
    assert removal["shiftDimension"] == "ROWS"

    # Mo-Mo was fixed in the sheet, so no card is left.
    assert (result.to_update, result.fixed_in_sheet) == (0, 1)
    assert w["'To Update'!A1:H2"][1][0] == "Nothing to update."


def test_to_update_tab_lists_open_cards(fake):  # noqa: F811
    c = cfg()
    (result,) = fake.upload(plan(build_rows(sample(), c), c), c, {})
    sheet = fake.sheets["2026 Accounts"]
    assert sheet.tabs[0] == TO_UPDATE
    table = writes(sheet)["'To Update'!A1:H5"]
    assert table[0][:6] == ["Date", "Amount (RM)", "Who / where", "Statement", "Recorded as", "Needs"]
    assert [row[5] for row in table[1:]] == ["Category", "what it was for", "Category", "what it was for, Category"]
    assert result.to_update == 4

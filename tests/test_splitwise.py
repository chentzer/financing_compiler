from datetime import date

import pytest

from fincomp.accounts import build_rows, plan
from fincomp.combine import match_transfers
from fincomp.config import Config, Trip
from fincomp.parsers import ParseError, build_parsers, find_parser
from fincomp.parsers.splitwise import SplitwiseParser, find_me

# Made-up group: you are "Jane Tan".
CSV = """Date,Description,Category,Cost,Currency,Bob Lim,Jane Tan,Mei Ling,Ahmad

2026-08-11,Train pass,General,3000.00,JPY,0.00,0.00,0.00,0.00
2026-08-11,Karaoke,General,40000.00,JPY,-10000.00,30000.00,-10000.00,-10000.00,
2026-08-11,Ahmad paid Jane T.,Payment,10000.00,JPY,0.00,-10000.00,0.00,10000.00
2026-08-12,Lunch,Dining out,4000.00,JPY,3000.00,-1000.00,-1000.00,-1000.00
2026-08-12,Jane T. paid Bob L.,Payment,1000.00,JPY,-1000.00,1000.00,0.00,0.00
2026-08-12,Mei L. paid Bob L.,Payment,1000.00,JPY,-1000.00,0.00,1000.00,0.00
2026-08-13,Gift shop,Home - Other,2000.00,JPY,-1000.00,0.00,1000.00,0.00

2026-10-20,Total balance, , ,JPY,0.00,0.00,0.00,0.00
""".encode()

JAPAN = Trip("Japan Trip", date(2026, 8, 10), date(2026, 8, 20), currency="Yen", rate=0.03)


def parse(config: Config, name="japan-trip_2026-10-20_export.csv"):
    return SplitwiseParser(config).parse_bytes(name, CSV)


def test_only_your_share_of_each_bill():
    rows = parse(Config(me=["Jane Tan"], trips=[JAPAN]))
    got = [(t.date.day, t.purpose, t.amount, t.counterparty, t.reference, t.internal) for t in rows]
    assert got == [
        (11, "Train pass", -3000.0, "", "", False),            # solo: yours, full cost, in yen
        (11, "Karaoke", -10000.0, "", "paid", False),          # you paid 40,000: your share
        (11, "Repayment", 10000.0, "Ahmad", "settle", True),   # paid back to you: not recorded
        (12, "Lunch", -1000.0, "Bob Lim", "share", False),     # Bob paid: your portion
        (12, "Paid back", -1000.0, "Bob Lim", "settle", True),  # paying Bob: not recorded either
    ]  # Mei paying Bob, and the gift shop (not yours), are left out
    assert rows[1].description == "Karaoke (you paid 40,000.00) · JPY 10,000.00"  # the whole bill in the remark
    assert rows[3].description == "Lunch · JPY 1,000.00" and {t.source for t in rows} == {"Splitwise"}
    assert {t.account for t in rows} == {"japan-trip"}  # same for every export of the group
    assert -sum(t.amount for t in rows if not t.internal) == 14000.0


def test_netting_doesnt_matter():
    """You paid Bob's 350 tote bag, Bob paid your 80 part of a pho, Bob pays you back 270: you spent 80."""
    csv = b"""Date,Description,Category,Cost,Currency,Bob Lim,Jane Tan

2026-08-11,Tote bag,General,350.00,MYR,-350.00,350.00
2026-08-11,Pho,Dining out,160.00,MYR,80.00,-80.00
2026-08-14,Bob L. paid Jane T.,Payment,270.00,MYR,270.00,-270.00
"""
    rows = SplitwiseParser(Config(me=["Jane Tan"])).parse_bytes("t.csv", csv)
    assert -sum(t.amount for t in rows if not t.internal) == 80.0


def test_into_accounts_trip_and_month():
    cfg = Config(me=["Jane Tan"], trips=[JAPAN])
    rows = build_rows(parse(cfg), cfg)
    tabs = {t.title: t for t in plan(rows, cfg)[2026]}
    # The whole group is the trip's, in the yen block.
    assert [(r.kind, r.item) for r in tabs["Japan Trip"].rows] == [
        ("spend", "Train pass"), ("spend", "Karaoke"), ("spend", "Lunch")]
    assert "August 2026" not in tabs or not tabs["August 2026"].rows


def test_whole_group_goes_to_its_trip_whatever_the_date():
    from fincomp.accounts import splitwise_trips
    from fincomp.models import Transaction

    def sw(d, amount, cur="VND", group="vietnam-trip"):
        return Transaction(date(2026, *d), "Splitwise", group, f"Pho · {cur} 1.00", amount)

    viet = Trip("Vietnam", date(2026, 11, 7), date(2026, 11, 10), currency="Dong", rate=0.00016)
    other = Trip("Penang", date(2026, 9, 12), date(2026, 9, 15))
    rows = [sw((9, 14), -1320.45, "MYR"), sw((9, 27), 1374.47, "MYR"), sw((11, 8), -64.0), sw((11, 16), -370.0)]
    cfg = Config(trips=[other, viet])
    assert splitwise_trips(rows, cfg.trips) == {"vietnam-trip": "Vietnam"}  # its currency, not Penang's dates
    assert {r.trip for r in build_rows(rows, cfg)} == {"Vietnam"}  # booking before, repayment, and after the end

    # An RM-only group: the trip most of its rows fall in; none at all: by date as before.
    rm = [sw((9, 13), -50.0, "MYR", "penang"), sw((9, 20), -30.0, "MYR", "penang")]
    assert splitwise_trips(rm, cfg.trips) == {"penang": "Penang"}
    assert splitwise_trips([sw((3, 1), -5.0, "MYR", "lunch")], cfg.trips) == {}


def test_splitwise_category_fills_yours():
    csv = CSV.replace(b"2026-08-13,Gift shop,Home - Other,2000.00,JPY,-1000.00,0.00,1000.00,0.00",
                      b"2026-08-13,Gift shop,Home - Other,2000.00,JPY,-1000.00,1000.00,0.00,0.00")
    cfg = Config(me=["Jane Tan"], trips=[JAPAN])
    (gift,) = [t for t in SplitwiseParser(cfg).parse_bytes("g.csv", csv) if t.purpose == "Gift shop"]
    assert gift.category == "Shopping"
    (row,) = [r for r in build_rows([gift], cfg)]
    assert row.category == "Shopping" and "category" not in row.needs


def test_never_paired_as_a_transfer_with_a_bank_row():
    from fincomp.models import Transaction

    cfg = Config(me=["Jane Tan"], trips=[JAPAN])
    sw = parse(cfg)
    bank = Transaction(date(2026, 8, 11), "Maybank", "acc", "SALARY", 1200.0)
    assert match_transfers(sw + [bank], 3) == []


def test_found_by_content_and_your_name():
    cfg = Config(me=["Jane Tan"], trips=[JAPAN])
    assert isinstance(find_parser("whatever.csv", CSV, build_parsers(cfg)), SplitwiseParser)
    assert find_me(["Bob Lim", "Jane Tan"], ["jane tan"]) == 1
    assert find_me(["Bob Lim", "Tan Mei Ling"], ["Mei Ling", ""]) == 1
    with pytest.raises(ParseError, match="which Splitwise member is you"):
        find_me(["Bob Lim"], ["Jane Tan"])


def test_rows_with_no_trip_in_their_currency_wait_the_rest_is_read():
    from fincomp.pipeline import parse_files

    mixed = CSV.replace(b"2026-08-13,Gift shop", b"2026-08-13,Bus,General,12.00,MYR,0.00,0.00,0.00,0.00\n2026-08-13,Gift shop")
    p = SplitwiseParser(Config(me=["Jane Tan"]))
    assert [t.purpose for t in p.parse_bytes("j.csv", mixed)] == ["Bus"]  # only the RM row
    assert p.missing == {"JPY": 5}  # Splitwise lines in yen: no trip in yen yet
    _, [res] = parse_files([("j.csv", mixed)], Config(me=["Jane Tan"]))
    assert res.ok and res.count == 1 and res.needs_trip == [{"currency": "JPY", "rows": 5}]

    # A trip in yen, even with no rate yet: every row, nothing waits.
    no_rate = Trip("Japan Trip", date(2026, 8, 10), date(2026, 8, 20), currency="JPY")
    _, [res] = parse_files([("j.csv", mixed)], Config(me=["Jane Tan"], trips=[no_rate]))
    assert res.count == 6 and res.needs_trip == []


YEN_BLOCK = [("Train pass", 3000.0), ("Karaoke", 10000.0), ("Lunch", 1000.0)]


def test_foreign_rows_go_in_the_trip_currency_block_with_keys():
    from fincomp.sheetplan import FIELDS, cash_range, data_ranges, locate

    cfg = Config(me=["Jane Tan"], trips=[JAPAN])
    rows = build_rows(parse(cfg), cfg)
    tab = next(t for t in plan(rows, cfg)[2026] if t.title == "Japan Trip")
    assert {r.currency for r in tab.rows} == {"JPY"}
    assert [(r.item, r.values()[3]) for r in tab.rows] == YEN_BLOCK  # money in is a negative yen amount
    assert cash_range("Japan Trip", 0) == "'Japan Trip'!S4:Y"  # Date..Remarks, key in the gap (Y)
    assert cash_range("Japan Trip", 0) in data_ranges([], ["Japan Trip"], cfg)
    found = locate({cash_range("Japan Trip", 0): [r.values() for r in tab.rows]})
    assert {k: (kind, row) for k, (_, kind, row, _) in found.items()} == \
        {r.key: ("cash0", 4 + i) for i, r in enumerate(tab.rows)}
    assert FIELDS["cash0"]["category"] == "U"


def test_sync_writes_the_yen_block_once():
    from fincomp import sheetplan

    cfg = Config(me=["Jane Tan"], trips=[JAPAN])
    tabs = plan(build_rows(parse(cfg), cfg), cfg)[2026]
    sheet_tabs = ["Sheet1"]
    values: dict[str, list[list]] = {}

    def sync():
        prepared = sheetplan.prepare(2026, list(sheet_tabs), tabs, cfg, not values)
        for added in prepared.add:
            sheet_tabs.insert(added.index, added.title)
        for gone in prepared.delete:
            sheet_tabs.remove(gone)
        read = {r: values.get(r, []) for r in prepared.reads}
        return sheetplan.finish(2026, prepared, {t: i for i, t in enumerate(sheet_tabs)}, read, tabs, cfg)

    done = sync()
    w = {d["range"]: d["values"] for d in done.data}
    yen = w["'Japan Trip'!S4:Y6"]
    assert [(r[1], r[3]) for r in yen] == YEN_BLOCK and all(r[6] for r in yen)
    assert not any(k.startswith(("'Japan Trip'!A4", "'Japan Trip'!J4")) for k in w)  # nothing in the RM blocks
    assert any(r.get("updateDimensionProperties", {}).get("range", {}).get("startIndex") == 24
               and r["updateDimensionProperties"]["properties"].get("hiddenByUser") for r in done.requests)  # Y hidden

    values[sheetplan.cash_range("Japan Trip", 0)] = yen  # what's in the sheet now
    again = sync()
    assert (again.added, again.already) == (0, 3)


def test_a_card_for_a_yen_row_says_yen():
    from fincomp.sheetplan import cards_from_values

    rows = [["2026-08-11", -3000, "", "Train pass · JPY 3,000.00", "Train pass", "Category", "Japan Trip", "k1"],
            ["2026-08-11", -12, "", "Bus · MYR 12.00", "Bus", "Category", "Japan Trip", "k2"]]
    assert [c["currency"] for c in cards_from_values(rows)] == ["JPY", ""]


def test_trip_screen_rows_have_their_keys():
    from fincomp.overview import trip_detail

    row = ["2026-08-11", "Hotel", "", 150, "", "Splitwise", "Hotel (you paid 600.00) · MYR 150.00", "k1"]
    row += [""] * (18 - len(row)) + ["2026-08-12", "Ramen", "", 1000, "", "Ramen · JPY 1,000.00", "k2"]
    t = trip_detail(JAPAN, [row])
    assert t["rm"][0]["key"] == "k1" and t["currencies"][0]["rows"][0]["key"] == "k2"

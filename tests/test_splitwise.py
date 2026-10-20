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


def test_what_you_paid_is_spending_repayments_are_earnings():
    rows = parse(Config(me=["Jane Tan"], trips=[JAPAN]))
    got = [(t.date.day, t.purpose, t.amount, t.counterparty, t.category) for t in rows]
    assert got == [
        (11, "Train pass", -90.0, "", ""),                 # solo: yours, full cost at 0.03
        (11, "Karaoke", -1200.0, "", ""),                  # you paid all of it
        (11, "Repayment", 300.0, "Ahmad", ""),            # paid back to you: earning
        (12, "Paid back", -30.0, "Bob Lim", ""),          # you paid Bob back: spending
    ]  # Lunch (Bob paid), Mei paying Bob, and the gift shop (not yours) are left out
    assert rows[1].description == "Karaoke · JPY 40,000.00" and {t.source for t in rows} == {"Splitwise"}
    assert {t.account for t in rows} == {"japan-trip"}  # same for every export of the group


def test_into_accounts_trip_and_month():
    cfg = Config(me=["Jane Tan"], trips=[JAPAN])
    rows = build_rows(parse(cfg), cfg)
    tabs = {t.title: t for t in plan(rows, cfg)[2026]}
    assert [r.item for r in tabs["Japan Trip"].rows] == ["Train pass", "Karaoke", "Paid back"]
    assert [(r.kind, r.item, r.who) for r in tabs["August 2026"].rows] == [("earn", "Repayment", "From Ahmad")]


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


def test_needs_the_trip_rate():
    with pytest.raises(ParseError, match="Settings › Trips"):
        parse(Config(me=["Jane Tan"]))
    with pytest.raises(ParseError, match="rate"):
        parse(Config(me=["Jane Tan"], trips=[Trip("Japan Trip", date(2026, 8, 10), date(2026, 8, 20), currency="JPY")]))

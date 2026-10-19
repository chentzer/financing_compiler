from datetime import date
from pathlib import Path

import pytest

from fincomp.accounts import build_rows
from fincomp.combine import match_transfers
from fincomp.config import Config
from fincomp.models import Transaction
from fincomp.parsers.base import ParseError
from fincomp.parsers.gx import parse_text

# Synthetic statement in the layout of GX Bank's text layer.
STATEMENT = """Page 1-2
 Jane Tan
Statements of Accounts
September 2026
GX Savings Account
Account number 8888-00000000-1
Date
Tarikh
1 Sep 2026
12:00 AM
Opening balance 10.00
2 Sep
09:15 PM
JANE TAN
Duitnow - Account
number
Fund transfer
+100.00 110.00
4 Sep
10:01 PM
Grab Ride
GX Account
-12.00 98.00
4 Sep
11:59 PM
Interest earned +0.01 98.01
5 Sep
12:18 AM
KEDAI MAKAN SEDAP
QR payment
-8.50 89.51
GX Bank Berhad Reg No. 000000000000
Page 2-2
Date
Tarikh
6 Sep
08:00 PM
BOB LIM
Duitnow - Account
number
movie tickets
-30.00 59.51
7 Sep
08:00 PM
JANE TAN
Duitnow - Account
number
Transfer
-50.00 9.51
+100.00 -100.50 +0.01 9.51
GX Bank Berhad Reg No. 000000000000
"""


def test_rows_types_and_self_transfers():
    txs = parse_text(STATEMENT)
    got = [(t.date, t.description.split(" - ")[0], t.amount, t.internal, t.counterparty, t.purpose) for t in txs]
    assert got == [
        (date(2026, 9, 2), "JANE TAN", 100.00, True, "JANE TAN", ""),
        (date(2026, 9, 4), "Grab Ride", -12.00, False, "", ""),
        (date(2026, 9, 4), "Interest earned", 0.01, False, "", "Interest earned"),
        (date(2026, 9, 5), "KEDAI MAKAN SEDAP", -8.50, False, "", ""),
        (date(2026, 9, 6), "BOB LIM", -30.00, False, "BOB LIM", "movie tickets"),
        (date(2026, 9, 7), "JANE TAN", -50.00, True, "JANE TAN", ""),
    ]
    assert {t.account for t in txs} == {"Savings ...0001"}


def test_into_accounts(tmp_path):
    cfg = Config(answers=tmp_path / "a.json", rules=[{"match": "GRAB", "category": "Transport"}])
    rows = build_rows(parse_text(STATEMENT), cfg)
    assert [(r.kind, r.item, r.amount, r.remarks, r.category) for r in rows] == [
        ("spend", "Grab Ride", 12.00, "GX Bank", "Transport"),
        ("earn", "Interest earned", 0.01, "GX Bank", ""),
        ("spend", "KEDAI MAKAN SEDAP", 8.50, "GX Bank", ""),  # QR to a shop: recorded, Category left to you
        ("spend", "Movie tickets", 30.00, "To Bob Lim", ""),
    ]


def test_self_transfer_pairs_with_other_bank():
    gx_out = next(t for t in parse_text(STATEMENT) if t.amount == -50.00)
    other_in = Transaction(date=date(2026, 9, 7), source="AEON Bank", account="Savings", description="JANE TAN",
                           amount=50.00, internal=True, transfer=True)
    assert len(match_transfers([gx_out, other_in], window_days=3)) == 1


def test_totals_must_add_up():
    with pytest.raises(ParseError, match="balance doesn't add up"):
        parse_text(STATEMENT.replace("-8.50 89.51", "-8.00 89.51"), file="x.pdf")
    with pytest.raises(ParseError, match="statement totals"):
        parse_text(STATEMENT.replace("+100.00 -100.50 +0.01 9.51", "+100.00 -99.50 +0.01 9.51"), file="x.pdf")

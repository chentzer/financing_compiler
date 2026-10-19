from datetime import date

import pytest

from fincomp.parsers.aeon import parse_text
from fincomp.parsers.base import ParseError

# Synthetic statement in the layout of AEON Bank's text layer.
STATEMENT = """AEON Bank (M) Berhad
eStatement
JANE TAN
Membership no. : 000000000000
Statement period
1 - 30 September 2026
Account summary
Savings Account-i
1234567890123
Total withdrawal -RM 1,170.00
Date Description Withdrawal Deposit Balance
01 Sep 26 Opening balance RM 100.00
02 Sep 26 JANE TAN - DuitNow - Transfer RM 1,000.00 RM 1,100.00
02 Sep 26 Savings - Transfer to Pot -RM 1,000.00 RM 100.00
05 Sep 26 BOB LIM - DuitNowID - lunch -RM 20.00 RM 80.00
Page 1 of 2
e-Statement
Transactions
Date Description Withdrawal Deposit Balance
06 Sep 26 Savings - Transfer to Account RM 150.00 RM 230.00
06 Sep 26 Jane Tan - DuitNow - concert tickets -RM 150.00 RM 80.00
16 Sep 26 AMY WONG - DuitNowQR - DuitNow QR RM 30.00 RM 110.00
30 Sep 26 Savings Account-i - Profit Earned RM 0.01 RM 110.01
30 Sep 26 Closing balance RM 110.01
Page 2 of 2
Account summary
Savings
Date Description Withdrawal Deposit Balance
01 Sep 26 Opening balance RM 500.00
02 Sep 26 Savings Account-i - Transfer to Pot RM 1,000.00 RM 1,500.00
06 Sep 26 Savings Account-i - Transfer to Account -RM 150.00 RM 1,350.00
30 Sep 26 Savings - Profit Earned RM 2.50 RM 1,352.50
30 Sep 26 Closing balance RM 1,352.50
"""


def test_accounts_signs_and_internal_moves():
    txs = parse_text(STATEMENT)
    got = [(t.account, t.description.split(" - ")[0], t.amount, t.internal, t.transfer) for t in txs]
    assert got == [
        ("Savings Account-i ...0123", "JANE TAN", 1000.00, True, True),  # from your other bank
        ("Savings Account-i ...0123", "Savings", -1000.00, True, False),  # into the pot
        ("Savings Account-i ...0123", "BOB LIM", -20.00, False, False),
        ("Savings Account-i ...0123", "Savings", 150.00, True, False),
        ("Savings Account-i ...0123", "Jane Tan", -150.00, True, True),  # to your other wallet
        ("Savings Account-i ...0123", "AMY WONG", 30.00, False, False),
        ("Savings Account-i ...0123", "Savings Account-i", 0.01, False, False),
        ("Savings", "Savings Account-i", 1000.00, True, False),
        ("Savings", "Savings Account-i", -150.00, True, False),
        ("Savings", "Savings", 2.50, False, False),
    ]
    assert txs[2].date == date(2026, 9, 5) and txs[2].type == "DuitNowID"


def test_balance_mismatch_fails_loudly():
    broken = STATEMENT.replace("lunch -RM 20.00 RM 80.00", "lunch -RM 25.00 RM 80.00")
    with pytest.raises(ParseError, match="balance doesn't add up"):
        parse_text(broken, file="x.pdf")


# ---- the recording rules on an AEON statement ---------------------------

from fincomp.accounts import build_rows, short_name
from fincomp.config import Config


def cfg(tmp_path, **kw):
    return Config(answers=tmp_path / "answers.json", **kw)


def test_rules_on_aeon_statement(tmp_path):
    c = cfg(tmp_path)
    rows = build_rows(parse_text(STATEMENT), c)
    got = [(r.kind, r.item, r.amount, r.remarks) for r in rows]
    # Rule 1: pot moves and transfers to/from "JANE TAN" are gone.
    # Rule 2: your spending, and money in from others.
    # Rule 3: AMY WONG's "DuitNow QR" says nothing: still recorded, with
    # what the statement gives, for the user to edit in the sheet.
    assert got == [
        ("spend", "Lunch", 20.00, "To Bob Lim"),
        ("earn", "QR payment", 30.00, "From Amy Wong"),
        ("earn", "Profit Earned", 0.01, "AEON Bank"),
        ("earn", "Profit Earned", 2.50, "AEON Bank"),
    ]
    # ...and it gets a card asking what it was for.
    assert [r.needs for r in rows if r.kind == "earn"][0] == ("purpose",)


def test_short_names():
    assert short_name("TAN MEI LING", {}) == "Mei Ling"
    assert short_name("CHAN WEI MING", {}) == "Wei Ming"
    assert short_name("AHMAD FAIZ BIN ISMAIL", {}) == "Ahmad Faiz"
    assert short_name("BOB LIM", {}) == "Bob Lim"
    assert short_name("TAN MEI LING", {"TAN MEI LING": "Zaiyi"}) == "Zaiyi"

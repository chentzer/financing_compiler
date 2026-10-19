from datetime import date

import pytest

from fincomp.accounts import build_rows
from fincomp.config import Config
from fincomp.parsers.base import ParseError
from fincomp.parsers.ryt import parse_text

# Synthetic statement in the layout of Ryt Bank's text layer.
STATEMENT = """Savings Account Statement
From 1 Sep 2026 to 30 Sep 2026
Savings Account No.  : / Nombor Akaun Simpanan 87 0000 1234
Account Holder / Pemegang Akaun
JANE TAN
Account Summary / Ringkasan Akaun
Main Savings
87-0000-1234
0.00 +0.05 -1,130.00 +1,250.00 120.05
Holiday Fund
Save Pocket
500.00 +2.10 0.00 0.00 502.10
Total (MYR)
Jumlah 500.00 +2.15 -1,130.00 +1,250.00 622.15
Account Transactions / Transaksi Akaun
1 Sep 2026 Opening balance 0.00
2 Sep 2026 From Holiday Fund
Money movement
Ref. ID: AAA1
+100.00 100.00
2 Sep 2026 From JANE TAN
Transfer
Fund transfer
Ref. ID: AAA2
+1,000.00 1,100.00
4 Sep 2026 SOME SOFTWARE SUB
Card ••0001
Ref. ID: AAA3 | Transaction date: 02 Sep 2026
-1,000.00
USD 220.00
Fee MYR 10.00
100.00
Savings Account Statement
From 1 Sep 2026 to 30 Sep 2026
5 Sep 2026 Daily interest payout
Ref. ID: AAA4
+0.05 100.05
12 Sep 2026 To BOB LIM AH KOW
Transfer
Dinner share
Ref. ID: AAA5
-30.00 70.05
27 Sep 2026 From AMY WONG MEI
Transfer
viet - flight n accoms
Ref. ID: AAA6
+100.00 170.05
27 Sep 2026 From CARL NG KAI
Transfer
Transfer
Ref. ID: AAA7
+50.00 220.05
29 Sep 2026 To JANE TAN
Transfer
Transfer
Ref. ID: AAA8
-100.00 120.05
Closing balance (MYR)
"""


def test_rows_and_classification():
    txs = parse_text(STATEMENT)
    got = [(t.date, t.amount, t.internal, t.counterparty or t.description, t.purpose) for t in txs]
    assert got == [
        (date(2026, 9, 2), 100.00, True, "From Holiday Fund - Money movement", ""),  # pocket move
        (date(2026, 9, 2), 1000.00, True, "JANE TAN", ""),  # from yourself
        (date(2026, 9, 2), -1000.00, False, "SOME SOFTWARE SUB", ""),  # card: transaction date
        (date(2026, 9, 5), 0.05, False, "Daily interest payout", "Interest earned"),
        (date(2026, 9, 12), -30.00, False, "BOB LIM AH KOW", "Dinner share"),
        (date(2026, 9, 27), 100.00, False, "AMY WONG MEI", "viet - flight n accoms"),
        (date(2026, 9, 27), 50.00, False, "CARL NG KAI", ""),
        (date(2026, 9, 29), -100.00, True, "JANE TAN", ""),
        (date(2026, 9, 30), 2.10, False, "Interest earned - Holiday Fund", "Interest earned"),  # pocket, from summary
    ]
    assert "USD 220.00" in txs[2].note and "Fee MYR 10.00" in txs[2].note


def test_into_accounts(tmp_path):
    cfg = Config(answers=tmp_path / "a.json")
    txs = parse_text(STATEMENT)
    assert [(r.kind, r.item, r.amount, r.remarks) for r in build_rows(txs, cfg)] == [
        ("spend", "SOME SOFTWARE SUB", 1000.00, "Ryt Bank"),
        ("earn", "Interest earned", 0.05, "Ryt Bank"),
        ("spend", "Dinner share", 30.00, "To Bob Lim Ah Kow"),  # 4-part names stay whole
        ("earn", "Viet - flight n accoms", 100.00, "From Wong Mei"),
        ("earn", "Transfer", 50.00, "From Ng Kai"),
        ("earn", "Interest earned", 2.10, "Ryt Bank"),
    ]


def test_balance_and_summary_must_add_up():
    with pytest.raises(ParseError, match="balance doesn't add up"):
        parse_text(STATEMENT.replace("-30.00 70.05", "-35.00 70.05"), file="x.pdf")
    with pytest.raises(ParseError, match="summary"):
        parse_text(STATEMENT.replace("+0.05 -1,130.00 +1,250.00", "+0.05 -1,130.00 +1,200.00"), file="x.pdf")

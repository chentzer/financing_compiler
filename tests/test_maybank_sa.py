from datetime import date

import pytest

from fincomp.accounts import build_rows, short_name
from fincomp.config import Config
from fincomp.parsers.base import ParseError
from fincomp.parsers.maybank_sa import parse_text

# Synthetic statement in the layout of Maybank2u's savings text layer.
# Detail lines are indented, and a page break splits the last transaction.
STATEMENT = """URUSNIAGA AKAUN/ ACCOUNT TRANSACTIONS
ENTRY DATE TRANSACTION DESCRIPTION TRANSACTION AMOUNT STATEMENT BALANCE
BEGINNING BALANCE 100.00
02/09/26 IBK FUND TFR TO A/C 500.00+ 600.00
   JANE TAN     *
   Transfer
   MBB CT-
02/09/26 FPX PAYMENT FR A/ 300.00- 300.00
   T172660000001      *
   AEON CREDIT SERVICE
   2609020000000001
06/09/26 FUND TRANSFER TO A/ 200.00+ 500.00
   TAN AH KOW     *
   2026-09CT
10/09/26 CMS-DIRECT DEBIT 150.00- 350.00
   PTPTN APPS DD ELMASI
   Y2025000000001
14/09/26 SVG GIRO CR 10.00+ 360.00
   AIA HEALTH SERVICES
   20260914000001
   DBPAY
28/09/26 SVG GIRO CR 3,000.00+ 3,360.00
   SOME EMPLOYER (MALAYSIA) SD
   sep26 netpay
   sep26 netpay
29/09/26 IBK FUND TFR FR A/C 1,000.00- 2,360.00
   JANE TAN     *

Malayan Banking Berhad (3813-K)
000001 SUBANG JAYA
JANE TAN
MUKA/ PAGE : 1
NOMBOR AKAUN
: 112233-445566
URUSNIAGA AKAUN/ ACCOUNT TRANSACTIONS
   Transfer
   MBB CT
ENDING BALANCE : 2,360.00
TOTAL CREDIT : 3,710.00
TOTAL DEBIT : 1,450.00
"""


def test_rows_and_classification():
    txs = parse_text(STATEMENT, own_payees=["AEON CREDIT SERVICE"])
    got = [(t.date, t.amount, t.internal, t.counterparty or t.description, t.purpose) for t in txs]
    assert got == [
        (date(2026, 9, 2), 500.00, True, "JANE TAN", ""),  # from yourself: ignored
        (date(2026, 9, 2), -300.00, True, "AEON CREDIT SERVICE", ""),  # paying your card: ignored
        (date(2026, 9, 6), 200.00, False, "TAN AH KOW", ""),  # reference only: ask
        (date(2026, 9, 10), -150.00, False, "PTPTN APPS DD ELMASI", ""),
        (date(2026, 9, 14), 10.00, False, "AIA HEALTH SERVICES", ""),
        (date(2026, 9, 28), 3000.00, False, "SOME EMPLOYER (MALAYSIA) SD", "sep26 netpay"),
        (date(2026, 9, 29), -1000.00, True, "JANE TAN", ""),  # details carried over the page break
    ]
    assert txs[1].transfer and {t.account for t in txs} == {"Savings ...5566"}


def test_into_accounts(tmp_path):
    cfg = Config(answers=tmp_path / "a.json")
    txs = parse_text(STATEMENT, own_payees=cfg.own_payees)
    assert [(r.kind, r.item, r.amount, r.who if r.counterparty else r.source) for r in build_rows(txs, cfg)] == [
        ("earn", "Transfer", 200.00, "From Ah Kow"),  # reference only: edit in the sheet
        ("spend", "PTPTN APPS DD ELMASI", 150.00, "Maybank"),
        ("earn", "Transfer", 10.00, "From Aia Health Services"),
        ("earn", "Sep26 netpay", 3000.00, "From Some Employer (Malaysia) Sd"),
    ]


def test_totals_must_add_up():
    with pytest.raises(ParseError, match="TOTAL DEBIT"):
        parse_text(STATEMENT.replace("TOTAL DEBIT : 1,450.00", "TOTAL DEBIT : 1,400.00"), file="x.pdf")


def test_company_names_stay_whole():
    assert short_name("SOME EMPLOYER (MALAYSIA) SD", {}) == "Some Employer (Malaysia) Sd"
    assert short_name("AIA HEALTH SERVICES", {}) == "Aia Health Services"
    assert short_name("LEONG KAH WAI", {}) == "Kah Wai"

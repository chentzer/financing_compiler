from datetime import date

from fincomp.config import Config
from fincomp.parsers import build_parsers, find_parser
from fincomp.parsers.maybank_cc import parse_text, resolve_year
from fincomp.parsers.tng import V1_COLUMNS, parse_v1_rows

MAYBANK_TEXT = """
STATEMENT OF ACCOUNT
28/12 29/12 SHOPEE MALAYSIA KUALA LUMPUR       120.00
02/01 03/01 GRAB*FOOD   KUALA LUMPUR MY          25.40
123456789012
05/01 05/01 PAYMENT VIA MBB ONLINE             500.00CR
05/01 05/01 RETAIL INTEREST RATE 15.00% P.A.      0.00
TOTAL                                          145.40
"""


def test_maybank_signs_years_and_references():
    txs = parse_text(MAYBANK_TEXT, date(2027, 1, 12), "card ...6700")
    assert [(t.date, t.amount) for t in txs] == [
        (date(2026, 12, 29), -120.00),  # December charge on a January statement
        (date(2027, 1, 3), -25.40),
        (date(2027, 1, 5), 500.00),
    ]
    assert txs[1].description == "GRAB*FOOD KUALA LUMPUR MY"
    assert txs[1].reference == "123456789012"
    assert txs[2].type == "Credit"
    assert txs[2].internal and not txs[0].internal  # card repayment isn't income


def test_resolve_year_july_statement_with_december():
    assert resolve_year("15/12", date(2026, 7, 12)) == date(2025, 12, 15)
    assert resolve_year("01/07", date(2026, 7, 12)) == date(2026, 7, 1)


def test_tng_v1_signs_and_goplus():
    rows = [
        ["01/07/2026", "Success", "Reload", "R1", "Maybank card", "", "RM50.00", "RM50.00"],
        ["02/07/2026", "Success", "Payment", "R2", "KK MART _1234567", "", "RM8.50", "RM41.50"],
        ["03/07/2026", "Success", "DUITNOW_TRANS FERTO", "R3", "Ali", "", "RM10.00", "RM31.50"],
        ["04/07/2026", "Success", "GO+ Cash In", "R4", "GO+ Cash In", "", "RM20.00", "RM11.50"],
        ["05/07/2026", "Success", "GO+ Daily Earnings", "R5", "GO+ Daily Earnings", "", "RM0.01", ""],
    ]
    txs = parse_v1_rows([dict(zip(V1_COLUMNS, r)) for r in rows])
    got = [(t.account, t.description, t.amount, t.internal) for t in txs]
    assert got == [
        ("eWallet", "Maybank card", 50.00, True),  # reloads are your own money
        ("eWallet", "KK MART", -8.50, False),
        ("eWallet", "Ali", -10.00, False),
        ("GO+", "GO+ Cash In", 20.00, True),
        ("GO+", "GO+ Daily Earnings", 0.01, False),
    ]


def test_detection_by_file_name():
    parsers = build_parsers(Config())
    assert find_parser("4000123412341234_20260712.pdf", b"", parsers).name == "maybank_cc"
    assert find_parser("tng_ewallet_transactions.pdf", b"", parsers).name == "tng"
    assert find_parser("Deposits-statement-1000000000-202609.pdf", b"", parsers).name == "aeon"
    assert find_parser("random.pdf", b"", parsers) is None

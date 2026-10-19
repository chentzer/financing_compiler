from datetime import date
from pathlib import Path

import pandas as pd

from fincomp.config import Config
from fincomp.parsers import build_parsers, find_parser
from fincomp.parsers.generic_csv import CsvParser
from fincomp.parsers.maybank_cc import parse_text, resolve_year
from fincomp.parsers.tng import parse_v1_tables, parse_v2_tables

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


def _v1_frame(rows):
    return pd.DataFrame(rows)


def test_tng_v1_signs_wrapping_and_goplus():
    frame = _v1_frame(
        [
            ["Date", "Status", "Transaction Type", "Reference", "Description", "Details", "Amount (RM)", "Wallet Balance"],
            ["01/07/2026", "Success", "Reload", "R1", "Maybank card", "", "RM50.00", "RM50.00"],
            ["02/07/2026", "Success", "Payment", "R2", "KK MART", "", "RM8.50", "RM41.50"],
            ["", "", "", "R2", "_1234567", "", "", ""],  # wrapped line
            ["03/07/2026", "Success", "DUITNOW_TRANS FERTO", "R3", "Ali", "", "RM10.00", "RM31.50"],
            ["04/07/2026", "Success", "GO+ Cash In", "R4", "GO+ Cash In", "", "RM20.00", "RM11.50"],
            ["05/07/2026", "Success", "GO+ Daily Earnings", "R5", "GO+ Daily Earnings", "", "RM0.01", ""],
        ]
    )
    txs = parse_v1_tables([frame])
    got = [(t.account, t.description, t.amount, t.internal) for t in txs]
    assert got == [
        ("eWallet", "Maybank card", 50.00, True),  # reloads are your own money
        ("eWallet", "KK MART", -8.50, False),
        ("eWallet", "Ali", -10.00, False),
        ("GO+", "GO+ Cash In", 20.00, True),
        ("GO+", "GO+ Daily Earnings", 0.01, False),
    ]


def test_tng_v2_groups_and_nets_quick_cash_in():
    frame = pd.DataFrame(
        [
            ["Details", "Transaction Type", "Reference No.", "Amount"],
            ["Starbucks", "", "", ""],
            ["01/07/2026 10:00", "Payment", "A1", "-RM12.00"],
            ["GO+ Quick Cash In", "", "", ""],
            ["02/07/2026 09:00", "GO+", "A2", "RM5.00"],
            ["eWallet Cash Out", "", "", ""],
            ["02/07/2026 09:00", "eWallet", "A3", "-RM5.00"],
            ["footer", "", "", ""],
            ["page 1", "", "", ""],
        ]
    )
    txs = parse_v2_tables([frame])
    # The date line closes each block, so the detail line above it belongs to it.
    assert [(t.date, t.amount) for t in txs] == [
        (date(2026, 7, 1), -12.00),
        (date(2026, 7, 2), 5.00),
        (date(2026, 7, 2), -5.00),
    ]
    assert txs[0].description == "Starbucks" and not txs[0].internal
    assert txs[1].internal and txs[2].internal


def test_csv_debit_credit_columns(tmp_path: Path):
    f = tmp_path / "cimb_2026_07.csv"
    f.write_text(
        "Bank export\n"
        "Date,Description,Withdrawal,Deposit\n"
        "01/07/2026,SALARY,,\"3,000.00\"\n"
        "03/07/2026,TNB BILL,120.50,\n"
        "31/07/2026,Closing balance,,\n",
        encoding="utf-8",
    )
    spec = {
        "name": "CIMB",
        "patterns": ["cimb*.csv"],
        "date_column": "Date",
        "date_format": "%d/%m/%Y",
        "description_column": "Description",
        "debit_column": "Withdrawal",
        "credit_column": "Deposit",
        "skip_rows": 1,
    }
    parser = CsvParser(Config(), spec)
    assert parser.matches(f)
    txs = parser.parse(f)
    assert [(t.date, t.description, t.amount) for t in txs] == [
        (date(2026, 7, 1), "SALARY", 3000.00),
        (date(2026, 7, 3), "TNB BILL", -120.50),
    ]
    # Same account for every monthly file, so overlaps dedupe.
    assert {t.account for t in txs} == {"CIMB"}


def test_detection_by_file_name():
    parsers = build_parsers(Config())
    assert find_parser("4000123412341234_20260712.pdf", b"", parsers).name == "maybank_cc"
    assert find_parser("tng_ewallet_transactions.pdf", b"", parsers).name == "tng"
    assert find_parser("Deposits-statement-1000000000-202609.pdf", b"", parsers).name == "aeon"
    assert find_parser("random.pdf", b"", parsers) is None

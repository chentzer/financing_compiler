from datetime import date

from fincomp.accounts import build_rows
from fincomp.config import Config
from fincomp.parsers.tng import V1_COLUMNS, parse_v1_rows


def statement():
    # Synthetic rows of TNG's 8-column statement.
    return [dict(zip(V1_COLUMNS, r)) for r in [
        ["2/9/2026", "Success", "Reload", "R1", "Quick Reload Payment (via GO+ Balance)", "D1", "RM20.00", "RM20.00"],
        ["2/9/2026", "Success", "DUITNOW_TRANS FERTO", "R2", "JANE TAN", "D2", "RM20.00", "RM0.00"],
        ["3/9/2026", "Success", "Transfer to Wallet", "R3", "Trip Leftovers", "D3", "RM9.50", "RM0.00"],
        ["5/9/2026", "Success", "Receive from Wallet", "R4", "BOB LIM AH", "D4", "RM37.00", "RM37.00"],
        ["7/9/2026", "Success", "TRANSIT_PASS", "R5", "", "D5", "RM50.00", "RM0.00"],
        ["11/9/2026", "Success", "Payment", "R6", "281498 - BrownDust2 - https://play.google.com/store/apps/d", "D6",
         "RM71.91", "RM0.00"],
        ["1/9/2026", "Success", "GO+ Daily Earnings", "M1", "Daily Interest", "D7", "RM0.0052", "RM63.48"],
        ["2/9/2026", "Success", "GO+ Daily Earnings", "M2", "Daily Interest", "D8", "RM0.0053", "RM0.00"],
        ["3/9/2026", "Success", "GO+ Cash In", "M3", "Via eWallet to GO+", "D9", "RM69.55", "RM69.55"],
        ["12/9/2026", "Failed", "Payment", "R7", "SOME SHOP", "D10", "RM5.00", "RM0.00"],
    ]]


def test_tng_rules():
    txs = parse_v1_rows(statement(), holder="JANE TAN")
    got = [(t.date, t.description, t.amount, t.internal) for t in txs]
    assert got == [
        (date(2026, 9, 2), "Quick Reload Payment (via GO+ Balance)", 20.00, True),  # reload: your money
        (date(2026, 9, 2), "JANE TAN", -20.00, True),  # DuitNow to yourself
        (date(2026, 9, 2), "GO+ Daily Earnings", 0.01, False),  # daily fractions: one row, on the last payout
        (date(2026, 9, 3), "Trip Leftovers", -9.50, False),
        (date(2026, 9, 3), "Via eWallet to GO+", 69.55, True),
        (date(2026, 9, 5), "BOB LIM AH", 37.00, False),
        (date(2026, 9, 7), "Transit Pass", -50.00, False),  # money out, not in
        (date(2026, 9, 11), "BrownDust2", -71.91, False),  # store link removed
        (date(2026, 9, 12), "SOME SHOP", -5.00, True),  # failed: no money moved
    ]
    assert txs[1].transfer  # pairs with the bank it came from


def test_tng_into_accounts():
    cfg = Config()
    txs = parse_v1_rows(statement(), holder="JANE TAN")
    assert [(r.kind, r.item, r.amount) for r in build_rows(txs, cfg)] == [
        ("earn", "GO+ earnings", 0.01),
        ("spend", "Trip Leftovers", 9.50),  # your note becomes the Item
        ("earn", "Transfer", 37.00),
        ("spend", "Transit Pass", 50.00),
        ("spend", "BrownDust2", 71.91),
    ]


def v1(date_, type_, desc, amount, balance, status="Success"):
    return {"Date": date_, "Status": status, "Type": type_, "Reference": "R", "Description": desc, "Details": "",
            "Amount": amount, "Balance": balance}


def test_tolls_and_unknown_types_follow_the_wallet_balance():
    from fincomp.parsers.tng import parse_v1_rows

    txs = parse_v1_rows([
        v1("8/8/2026", "Reload", "Quick Reload Payment (via GO+ Balance)", "RM2.30", "RM2.30"),
        v1("8/8/2026", "PayDirect Payment", "SOME TOLL PLAZA", "RM2.30", "RM0.00"),  # a toll: spending
        v1("9/8/2026", "Reload", "Quick Reload Payment (via GO+ Balance)", "RM5.00", "RM5.00"),
        v1("9/8/2026", "Mystery Charge", "SOME NEW THING", "RM4.00", "RM1.00"),  # a type TNG adds later
        v1("10/8/2026", "Receive from Wallet", "BOB LIM", "RM10.00", "RM11.00"),
    ])
    assert [(t.description, t.amount) for t in txs if not t.internal] == [
        ("SOME TOLL PLAZA", -2.30), ("SOME NEW THING", -4.00), ("BOB LIM", 10.00),
    ]


def test_paydirect_is_always_spending_even_when_rows_are_out_of_order():
    from fincomp.parsers.tng import parse_v1_rows

    # Same-day rows listed out of order: the balance seems to go up by the toll's amount.
    txs = parse_v1_rows([
        v1("8/8/2026", "Reload", "Quick Reload Payment (via GO+ Balance)", "RM10.00", "RM7.70"),
        v1("8/8/2026", "PayDirect Payment", "SOME TOLL PLAZA", "RM2.30", "RM10.00"),
        v1("8/8/2026", "PayDirect Payment", "SOME CAR PARK", "RM3.00", "RM7.00"),
    ])
    assert [(t.description, t.amount) for t in txs if not t.internal] == [
        ("SOME TOLL PLAZA", -2.30), ("SOME CAR PARK", -3.00),
    ]

from datetime import date
from pathlib import Path

import pytest

from fincomp.accounts import build_rows
from fincomp.config import Config
from fincomp.parsers import build_parsers, find_parser
from fincomp.parsers.aeon_credit import clean_merchant, parse_text
from fincomp.parsers.base import ParseError

# Synthetic statement in the layout of AEON Credit's text layer.
STATEMENT = """CREDIT CARD STATEMENT / TAX INVOICE
AEON CREDIT SERVICE (M) BHD
Page 3 / 5
YOUR PREVIOUS STATEMENT BALANCE 100.00
4000000000001111 MS JANE TAN
02 Sep 2026 01 Sep 2026 KEDAI KOPI SATU PETALING JAYAMY 12.50
02 Sep 2026 02 Sep 2026 FPX PAYMENT TRANSFER CR 100.00
02 Sep 2026 02 Sep 2026 POINT REDEMPTION FOR CASH CR 5.00
16 Sep 2026 14 Sep 2026 AIRASIA-AKRB-FLT-MYR KUALALUMPUR MY 1,250.00
22 Sep 2026 20 Sep 2026 Shopee MY Marketplace KualaLumpur MY 40.00
4000000000002222 MS JANE TAN
25 Sep 2026 25 Sep 2026 CASHBACK CR 2.00
25 Sep 2026 24 Sep 2026 FITNESS ACADEMY MY 30.00
TOTAL CHARGES OF THIS MONTH 1,332.50
CLOSING BALANCE 1,325.50
"""


def test_charges_cards_and_dates():
    txs = parse_text(STATEMENT)
    charges = [(t.account, t.date, t.description, t.amount) for t in txs if not t.internal]
    assert charges == [
        ("card ...1111", date(2026, 9, 1), "KEDAI KOPI SATU", -12.50),  # transaction date, not posting
        ("card ...1111", date(2026, 9, 14), "AIRASIA-AKRB-FLT-MYR", -1250.00),
        ("card ...1111", date(2026, 9, 20), "Shopee MY Marketplace", -40.00),
        ("card ...2222", date(2026, 9, 24), "FITNESS ACADEMY", -30.00),
    ]


def test_cr_rows_are_ignored():
    txs = parse_text(STATEMENT)
    credits = [t for t in txs if t.amount > 0]
    assert [t.description for t in credits] == ["FPX PAYMENT TRANSFER", "POINT REDEMPTION FOR CASH", "CASHBACK"]
    assert all(t.internal for t in credits)
    # Only the card payment can be paired with a bank transfer.
    assert [t.transfer for t in credits] == [True, False, False]
    assert not any(t.amount > 0 for t in [r for r in txs if not r.internal])


def test_charges_are_all_recorded(tmp_path):
    txs = parse_text(STATEMENT)
    cfg = Config(answers=tmp_path / "a.json", rules=[{"match": "SHOPEE", "category": "Shopping"}])
    assert [(r.item, r.category, r.who if r.counterparty else r.source) for r in build_rows(txs, cfg)] == [
        ("KEDAI KOPI SATU", "", "AEON Credit"),
        ("AIRASIA-AKRB-FLT-MYR", "", "AEON Credit"),
        ("Shopee MY Marketplace", "Shopping", "AEON Credit"),
        ("FITNESS ACADEMY", "", "AEON Credit"),
    ]
    # Charges without a Category get a card for it.
    assert [r.needs for r in build_rows(txs, cfg)] == [("category",), ("category",), (), ("category",)]


def test_totals_must_add_up():
    with pytest.raises(ParseError, match="charges"):
        parse_text(STATEMENT.replace("FITNESS ACADEMY MY 30.00", "FITNESS ACADEMY MY 3.00"), file="x.pdf")


def test_clean_merchant():
    assert clean_merchant("AEON BIG-JAYA ONE PETALING JAYAMY") == "AEON BIG-JAYA ONE"
    assert clean_merchant("TEXAS SOGO KUALA LUMPUR MY") == "TEXAS SOGO"
    assert clean_merchant("ATAP BY PAGI COFFEE CO Subang Jaya MY") == "ATAP BY PAGI COFFEE CO"
    assert clean_merchant("AIA VITALITY FEE VA51910667 MY") == "AIA VITALITY FEE VA51910667"
    assert clean_merchant("THE ACADEMY") == "THE ACADEMY"


def test_detected_by_content_not_just_name(tmp_path, monkeypatch):
    parsers = build_parsers(Config())
    name = "September 2026 e-statement.pdf"
    from fincomp.parsers import aeon_credit
    monkeypatch.setattr(aeon_credit.AeonCreditParser, "text", lambda self, n, d, pw: "AEON CREDIT SERVICE (M) BHD")
    assert find_parser(name, b"", parsers).name == "aeon_credit"
    monkeypatch.setattr(aeon_credit.AeonCreditParser, "text", lambda self, n, d, pw: "SOME OTHER BANK")
    assert find_parser(name, b"", parsers) is None

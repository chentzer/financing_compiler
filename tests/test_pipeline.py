from datetime import date

import pytest

from fincomp import pipeline
from fincomp.config import Config
from fincomp.models import Transaction
from fincomp.parsers import tng
from fincomp.parsers.base import ParseError, Parser, PasswordNeeded


# ---- TNG table rebuilt from text positions (no camelot) -------------------


class FakePage:
    def __init__(self, items):
        self.items = items


def test_tng_rows_from_positions(monkeypatch):
    # (row position, column position, text) as the rotated TNG page gives them.
    page1 = [
        (29.3, 20.0, "3/9/2026"), (29.3, 80.0, "Success"), (29.3, 140.0, "Transfer to Wallet"),
        (29.3, 230.0, "20260903000\n"), (40.9, 230.0, "2170"), (29.3, 295.0, "Trip Leftovers"),
        (29.3, 460.0, "2026090300000000000000TNGOW3\n"), (29.3, 676.4, "RM69.55"), (29.3, 782.0, "RM0.00"),
        (75.3, 20.0, "7/9/2026"), (75.3, 80.0, "Success"), (75.3, 140.0, "DUITNOW_TRANS\n"), (86.9, 140.0, "FERTO"),
        (75.3, 230.0, "R2"), (75.3, 295.0, "JANE TAN"), (75.3, 676.4, "RM50.00"), (75.3, 782.0, "RM0.00"),
        (97.0, 295.0, "wrapped"),  # still part of the 7/9 row
        (507.1, 20.0, "GO+ TRANSACTION"),  # section title: ends the row
        (525.3, 20.0, "Date"), (525.3, 295.0, "Description"),  # header: not a row
        (555.3, 20.0, "*This is a system generated email."),
    ]
    page2 = [
        (29.3, 20.0, "1/9/2026"), (29.3, 80.0, "Success"), (29.3, 140.0, "GO+ Daily Earnings"),
        (29.3, 230.0, "MMF1"), (29.3, 295.0, "Daily Interest"), (29.3, 676.4, "RM0.0052"), (29.3, 782.0, "RM63.48"),
    ]
    monkeypatch.setattr(tng, "_text_items", lambda page: page.items)

    class Reader:
        pages = [FakePage(page1), FakePage(page2)]

    rows = tng.read_v1_rows(Reader())
    assert [(r["Date"], r["Type"], r["Description"], r["Amount"]) for r in rows] == [
        ("3/9/2026", "Transfer to Wallet", "Trip Leftovers", "RM69.55"),
        ("7/9/2026", "DUITNOW_TRANS FERTO", "JANE TAN wrapped", "RM50.00"),
        ("1/9/2026", "GO+ Daily Earnings", "Daily Interest", "RM0.0052"),
    ]
    txs = tng.parse_v1_rows(rows, holder="JANE TAN")
    assert [(t.description, t.amount, t.internal) for t in txs] == [
        ("GO+ Daily Earnings", 0.01, False),
        ("Trip Leftovers", -69.55, False),
        ("JANE TAN wrapped", -50.00, False),  # name + wrapped text isn't exactly you
    ]


# ---- pipeline -------------------------------------------------------------


def t(day, amount, desc, file, source="Bank A", **kw):
    return Transaction(date=date(2026, 9, day), source=source, account="acc", description=desc,
                       amount=amount, file=file, **kw)


class FakeParser(Parser):
    name = "fake"
    label = "Bank A"
    default_patterns = ["*.pdf"]
    contents: dict[bytes, list[Transaction]] = {}

    def parse_bytes(self, name, data, password=""):
        if data == b"locked" and password != "secret":
            raise PasswordNeeded(name, self.name)
        if data == b"broken":
            raise ParseError(f"{name}: balance doesn't add up")
        return [Transaction(**{**vars(x), "file": name}) for x in self.contents[data]]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(pipeline, "build_parsers", lambda config: [FakeParser(config)])
    return FakeParser


def test_results_per_file(fake):
    fake.contents = {b"sep": [t(1, -10.0, "Shop", "")]}
    out = pipeline.compile_statements(
        [("a.pdf", b"sep"), ("b.pdf", b"locked"), ("c.pdf", b"broken"), ("notes.txt", b"x")], Config()
    )
    got = [(f.name, f.ok, f.count, f.needs_password) for f in out.files]
    assert got == [("a.pdf", True, 1, ""), ("b.pdf", False, 0, "fake"), ("c.pdf", False, 0, ""), ("notes.txt", False, 0, "")]
    assert out.files[3].error == "not a statement fincomp recognises"


def test_saved_password_unlocks(fake):
    fake.contents = {b"locked": [t(1, -10.0, "Shop", "")]}
    out = pipeline.compile_statements([("b.pdf", b"locked")], Config(passwords={"fake": "secret"}))
    assert out.files[0].ok and len(out.rows) == 1


def test_earlier_uploads_pair_with_new_and_reupload_replaces(fake):
    # Bank B's statement was uploaded last week; today's Bank A one pairs with it.
    earlier = [t(2, 50.0, "JANE TAN", "b.pdf", source="Bank B", internal=True, transfer=True, counterparty="JANE TAN")]
    fake.contents = {b"a": [t(2, -50.0, "JANE TAN", "", internal=True, transfer=True, counterparty="JANE TAN"),
                            t(3, -8.0, "Shop", "")]}
    out = pipeline.compile_statements([("a.pdf", b"a")], Config(), earlier=earlier)
    assert len(out.matches) == 1
    assert [(x.description, x.file) for x in out.parsed] == [("JANE TAN", "a.pdf"), ("Shop", "a.pdf")]
    assert not any("transfer" in x.note for x in out.parsed)  # stored as parsed, before pairing

    # Uploading a.pdf again replaces its earlier copy instead of doubling it.
    again = pipeline.compile_statements([("a.pdf", b"a")], Config(), earlier=earlier + out.parsed)
    assert sorted(x.description for x in again.transactions) == ["JANE TAN", "JANE TAN", "Shop"]

"""Splitwise rows that are also on a bank statement are recorded once."""

from datetime import date

import pytest

from fincomp import pipeline
from fincomp.accounts import to_update_table
from fincomp.combine import match_splitwise
from fincomp.config import Config
from fincomp.models import Transaction
from fincomp.parsers.base import Parser
from fincomp.sheetplan import cards_from_values


def sw(day, amount, desc="Dinner", cur="MYR", money=None, **kw):
    money = abs(amount) if money is None else money
    return Transaction(date=date(2026, 9, day), source="Splitwise", account="Penang", amount=amount,
                       description=f"{desc} · {cur} {money:,.2f}", purpose=desc, file="penang.csv", **kw)


def bank(day, amount, desc="SUSHI MENTAI", source="Maybank Card", **kw):
    return Transaction(date=date(2026, 9, day), source=source, account="card", amount=amount, description=desc,
                       file="card.pdf", **kw)


def test_same_rm_amount_is_a_match():
    s, b = sw(5, -120.0), bank(6, -120.0)
    other = bank(5, -45.0, "GRAB")
    got = match_splitwise([s, b, other])
    assert [(m.splitwise, m.bank, m.sure) for m in got] == [(s, b, True)]


def test_direction_window_and_own_transfers():
    s = sw(5, -120.0)
    assert match_splitwise([s, bank(5, 120.0)]) == []  # money in vs money out
    assert match_splitwise([s, bank(12, -120.0)]) == []  # too far apart
    assert match_splitwise([s, bank(5, -120.0, internal=True)]) == []  # between your own accounts


def test_repayment_matches_the_transfer_in():
    s = sw(8, 40.0, "Repayment", counterparty="Bob Lim")
    b = bank(8, 40.0, "DUITNOW BOB LIM", source="GX Bank", counterparty="BOB LIM")
    assert [(m.bank, m.sure) for m in match_splitwise([s, b])] == [(b, True)]


def test_foreign_currency_close_or_maybe():
    s = sw(5, -101.5, cur="JPY", money=3500)  # 3,500 yen at the trip's rate
    one = bank(6, -103.2)  # card's own rate: 1.7% off
    assert [(m.bank, m.sure) for m in match_splitwise([s, one])] == [(one, True)]
    two = bank(5, -100.9, "LAWSON")  # two charges that close: only a maybe, nearest amount
    assert [(m.bank, m.sure) for m in match_splitwise([s, one, two])] == [(two, False)]
    far = bank(6, -108.0)  # 6% off: a maybe
    assert [(m.bank, m.sure) for m in match_splitwise([s, far])] == [(far, False)]
    assert match_splitwise([s, bank(6, -120.0)]) == []  # 18% off: not the same
    assert match_splitwise([sw(5, -101.5), bank(6, -103.2)]) == []  # RM rows only match exactly


def test_exact_partner_is_not_taken_by_a_converted_row():
    rm = sw(5, -100.0)
    yen = sw(5, -101.0, cur="JPY", money=3500)
    b = bank(5, -100.0)
    got = match_splitwise([yen, rm, b])
    assert [(m.splitwise, m.sure) for m in got] == [(rm, True)]


# ---- what gets recorded ---------------------------------------------------------------


def items(rows):
    return sorted((r.source, r.item, r.category) for r in rows)


def test_both_new_keeps_the_bank_row_with_splitwise_details():
    config = Config()
    s = sw(5, -120.0, "Sushi dinner", category="Food")
    out = pipeline.compile_transactions([s, bank(5, -120.0)], config)
    assert items(out.rows) == [("Maybank Card", "Sushi dinner", "Food")]
    assert len(out.removed) == 1 and out.removed[0][0] in config.removed


def test_new_statement_after_splitwise_drops_the_bank_row(monkeypatch):
    s = sw(5, -120.0, "Sushi dinner", category="Food")

    class Card(Parser):
        name, label, default_patterns = "card", "Maybank Card", ["*.pdf"]

        def parse_bytes(self, name, data, password=""):
            return [bank(5, -120.0)]

    monkeypatch.setattr(pipeline, "build_parsers", lambda config: [Card(config)])
    config = Config()
    out = pipeline.compile_statements([("card.pdf", b"x")], config, earlier=[s])
    # The Splitwise row is already in the sheet: the statement's copy stays out.
    assert items(out.rows) == [("Splitwise", "Sushi dinner", "Food")]
    assert len(out.removed) == 1

    # Next upload: settled, nothing new is removed and nothing doubles.
    again = pipeline.compile_statements([], config, earlier=[s] + out.parsed)
    assert items(again.rows) == [("Splitwise", "Sushi dinner", "Food")] and again.removed == []


def test_both_already_recorded_asks_on_the_splitwise_card():
    config = Config()
    s, b = sw(5, -120.0, category="Food"), bank(5, -120.0, category="Food")
    out = pipeline.compile_transactions([s, b], config, fresh=set())
    assert out.removed == [] and len(out.rows) == 2
    card = next(r for r in out.rows if r.source == "Splitwise")
    assert card.needs == ("twin",) and card.twin.startswith("2026-09-05 Maybank Card RM 120.00 SUSHI MENTAI #")

    # Its To Update line reads back as a card with the bank row's key.
    tab = next(t for ts in out.tabs.values() for t in ts if any(r is card for r in t.rows))
    table = to_update_table([tab])
    got = cards_from_values(table[1:])
    bank_key = next(r.key for r in out.rows if r.source == "Maybank Card")
    assert [(c["key"], c["twinKey"], c["twin"]) for c in got] == \
        [(card.key, bank_key, "2026-09-05 Maybank Card RM 120.00 SUSHI MENTAI")]

    # "Different": the question doesn't come back.
    config.reviewed.add(f"{card.key}~{bank_key}")
    again = pipeline.compile_transactions([s, b], config, fresh=set())
    assert all(not r.needs for r in again.rows)


def test_a_maybe_asks_even_when_new():
    s = sw(5, -101.5, cur="JPY", money=3500, category="Food")
    out = pipeline.compile_transactions([s, bank(5, -108.0, category="Food")], Config())
    assert out.removed == [] and len(out.rows) == 2
    assert next(r for r in out.rows if r.source == "Splitwise").needs == ("twin",)


def test_twin_card_with_other_needs():
    s = sw(5, -120.0, "Dinner")  # no category: asks for one too
    out = pipeline.compile_transactions([s, bank(5, -120.0)], Config(), fresh=set())
    card = next(r for r in out.rows if r.source == "Splitwise")
    assert card.needs == ("category", "twin")
    tab = next(t for ts in out.tabs.values() for t in ts if any(r is card for r in t.rows))
    [got] = [c for c in cards_from_values(to_update_table([tab])[1:]) if c["key"] == card.key]
    assert got["needsCategory"] and got["twinKey"]


@pytest.mark.parametrize("removed", ["splitwise", "bank"])
def test_a_row_you_removed_settles_it(removed):
    config = Config()
    s, b = sw(5, -120.0, category="Food"), bank(5, -120.0, category="Food")
    first = pipeline.compile_transactions([s, b], Config(), fresh=set())
    keys = {r.source: r.key for r in first.rows}
    config.removed.add(keys["Splitwise" if removed == "splitwise" else "Maybank Card"])
    out = pipeline.compile_transactions([s, b], config, fresh=set())
    assert len(out.rows) == 1 and not out.rows[0].needs and out.removed == []

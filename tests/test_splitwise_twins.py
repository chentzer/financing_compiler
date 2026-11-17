"""Splitwise rows that are also on a bank statement are recorded once."""

from datetime import date

import pytest

from fincomp import pipeline
from fincomp.accounts import _keyed, to_update_table
from fincomp.combine import match_splitwise
from fincomp.config import Config, Trip
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
    s = sw(5, -3500.0, cur="JPY")  # 3,500 yen: RM 101.50 at the trip's rate
    rate = lambda t: 0.029  # noqa: E731
    one = bank(6, -103.2)  # card's own rate: 1.7% off
    assert [(m.bank, m.sure) for m in match_splitwise([s, one], rate)] == [(one, True)]
    two = bank(5, -100.9, "LAWSON")  # two charges that close: only a maybe, nearest amount
    assert [(m.bank, m.sure) for m in match_splitwise([s, one, two], rate)] == [(two, False)]
    far = bank(6, -108.0)  # 6% off: a maybe
    assert [(m.bank, m.sure) for m in match_splitwise([s, far], rate)] == [(far, False)]
    assert match_splitwise([s, bank(6, -120.0)], rate) == []  # 18% off: not the same
    assert match_splitwise([s, one]) == []  # no rate yet: not compared
    assert match_splitwise([sw(5, -101.5), bank(6, -103.2)], rate) == []  # RM rows only match exactly


def test_exact_partner_is_not_taken_by_a_converted_row():
    rm = sw(5, -100.0)
    yen = sw(5, -3500.0, cur="JPY")
    b = bank(5, -100.0)
    got = match_splitwise([yen, rm, b], lambda t: 0.0286)
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
    s = sw(5, -3500.0, cur="JPY", category="Food")
    japan = Trip("Japan", date(2026, 9, 1), date(2026, 9, 10), currency="JPY", rate=0.029)
    out = pipeline.compile_transactions([s, bank(5, -108.0, category="Food")], Config(trips=[japan]))
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


# ---- paying a friend back: your portion is already counted, so the DuitNow isn't -----


def settle(day, amount):
    return Transaction(date=date(2026, 9, day), source="Splitwise", account="penang", amount=amount,
                       description=f"Jane T. paid Bob L. · MYR {abs(amount):,.2f}", purpose="Paid back",
                       reference="settle", internal=True, counterparty="Bob Lim", file="penang.csv")


def test_a_new_duitnow_that_is_a_repayment_asks():
    # It may be money back for a bill you count whole, so it's never taken out by itself.
    s, b = settle(8, -270.0), bank(9, -270.0, "DUITNOW BOB LIM", source="GX Bank")
    out = pipeline.compile_transactions([s, b], Config())
    (row,) = out.rows
    assert row.source == "GX Bank" and row.needs[-1] == "twin" and out.removed == []


def test_a_duitnow_already_recorded_gets_a_card():
    config = Config()
    s, b = settle(8, -270.0), bank(9, -270.0, "DUITNOW BOB LIM", source="GX Bank")
    out = pipeline.compile_transactions([s, b], config, fresh=set())
    (row,) = out.rows
    assert row.source == "GX Bank" and row.needs[-1] == "twin" and row.twin.startswith("2026-09-08 Splitwise Jane T.")
    s_key = next(k for k, t in _keyed([s, b]) if t is s)
    config.reviewed.add(f"{row.key}~{s_key}")  # "Different"
    again = pipeline.compile_transactions([s, b], config, fresh=set())
    assert "twin" not in again.rows[0].needs


def test_your_portion_never_matches_a_bank_row():
    share = sw(5, -80.0, "Pho (your share of 160.00)", reference="share")
    assert match_splitwise([share, bank(5, -80.0)]) == []


def test_money_paid_back_to_you_isnt_counted_your_share_is():
    back = Transaction(date=date(2026, 9, 8), source="Splitwise", account="penang", amount=270.0,
                       description="Bob L. paid Jane T. · MYR 270.00", purpose="Repayment", reference="settle",
                       internal=True, counterparty="Bob Lim", file="penang.csv")
    out = pipeline.compile_transactions([back, bank(9, 270.0, "DUITNOW BOB LIM", source="GX Bank")], Config())
    (row,) = out.rows
    assert row.kind == "earn" and row.needs[-1] == "twin"  # Same takes it out: their share was never yours


def test_the_card_charge_for_a_bill_you_paid_gives_way_to_your_share():
    paid = Transaction(date=date(2026, 9, 5), source="Splitwise", account="penang", amount=-30.0,
                       description="Dinner (you paid 120.00) · MYR 30.00", purpose="Dinner", reference="paid",
                       file="penang.csv")
    out = pipeline.compile_transactions([paid, bank(5, -120.0)], Config())
    assert [(r.source, r.amount, r.remarks) for r in out.rows] == \
        [("Splitwise", 30.0, "Dinner (you paid 120.00) · MYR 30.00")] and len(out.removed) == 1


def test_a_bill_you_count_whole():
    paid = Transaction(date=date(2026, 9, 5), source="Splitwise", account="penang", amount=-1154.4,
                       description="Flight (you paid 5,772.00) · MYR 1,154.40", purpose="Flight", reference="paid",
                       file="penang.csv")
    config = Config()
    (row,) = pipeline.compile_transactions([paid], config).rows
    assert row.amount == 1154.4  # your share
    config.reviewed.add(f"whole:{row.key}")
    (again,) = pipeline.compile_transactions([paid], config).rows
    assert (again.key, again.amount) == (row.key, 5772.0)  # same row, the whole bill

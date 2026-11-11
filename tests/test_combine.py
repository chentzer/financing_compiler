from datetime import date

from fincomp.combine import dedupe, match_transfers
from fincomp.models import Transaction


def tx(d, source, amount, desc="x", file="a.pdf", account="acc"):
    return Transaction(date=d, source=source, account=account, description=desc, amount=amount, file=file)


def test_dedupe_keeps_same_day_repeats_within_one_file():
    jul1 = date(2026, 7, 1)
    rows = [
        tx(jul1, "TNG", -5.0, "coffee", "june.pdf"),
        tx(jul1, "TNG", -5.0, "coffee", "june.pdf"),
        tx(jul1, "TNG", -5.0, "coffee", "july.pdf"),  # overlap: same day in next statement
        tx(jul1, "TNG", -5.0, "coffee", "july.pdf"),
        tx(jul1, "TNG", -9.0, "lunch", "july.pdf"),
    ]
    kept, dropped = dedupe(rows)
    assert dropped == 2
    assert sorted(t.amount for t in kept) == [-9.0, -5.0, -5.0]


def test_card_reload_of_wallet_is_internal():
    card = tx(date(2026, 7, 1), "Maybank Card", -50.0, "TNG RELOAD")
    wallet_in = tx(date(2026, 7, 2), "TNG eWallet", 50.0, "Reload")
    wallet_in.internal = wallet_in.transfer = True  # as the TNG parser marks a reload
    spend = tx(date(2026, 7, 2), "TNG eWallet", -50.0, "Shop")
    unrelated = tx(date(2026, 7, 20), "TNG eWallet", 50.0, "From Ali")

    matches = match_transfers([card, wallet_in, spend, unrelated], window_days=3)

    assert len(matches) == 1 and matches[0].out is card and matches[0].into is wallet_in
    assert card.internal and wallet_in.internal
    assert not spend.internal and not unrelated.internal


def test_same_amount_from_a_friend_is_not_a_transfer():
    dinner = tx(date(2026, 7, 1), "Maybank Card", -50.0, "NASI KANDAR")
    friend = tx(date(2026, 7, 2), "TNG eWallet", 50.0, "BOB LIM")
    assert match_transfers([dinner, friend], window_days=3) == []
    assert not dinner.internal and not friend.internal


def test_bank_payment_pairs_with_card_repayment_marked_transfer():
    bank = tx(date(2026, 7, 5), "Maybank Savings", -500.0, "CARD PAYMENT")
    card = tx(date(2026, 7, 6), "Maybank Card", 500.0, "PAYMENT VIA MBB")
    card.internal = card.transfer = True
    assert len(match_transfers([bank, card], window_days=3)) == 1
    assert bank.internal


def test_same_account_is_never_a_transfer():
    a = tx(date(2026, 7, 1), "TNG eWallet", -20.0)
    b = tx(date(2026, 7, 1), "TNG eWallet", 20.0)
    assert match_transfers([a, b], window_days=3) == []


def test_known_transfers_pair_before_ordinary_rows():
    # Same day: a RM6.30 Grab ride on GX, and RM6.30 sent from TNG to GX.
    grab = tx(date(2026, 9, 16), "GX Bank", -6.30, "Grab Ride")
    tng_out = tx(date(2026, 9, 16), "TNG eWallet", -6.30, "JANE TAN")
    gx_in = tx(date(2026, 9, 16), "GX Bank", 6.30, "JANE TAN")
    tng_out.internal = tng_out.transfer = True
    gx_in.internal = gx_in.transfer = True

    (m,) = match_transfers([grab, tng_out, gx_in], window_days=3)
    assert (m.out, m.into) == (tng_out, gx_in)
    assert not grab.internal  # still counted as spending

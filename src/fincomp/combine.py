from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .models import Transaction


def _key(t: Transaction) -> tuple:
    return (t.source, t.account, t.date, t.description, round(t.amount, 2), t.type, t.reference)


def dedupe(transactions: list[Transaction]) -> tuple[list[Transaction], int]:
    """Drop rows repeated across overlapping statements.

    Identical rows inside one file are real (two RM5 coffees on the same
    day), so for each distinct row we keep as many copies as the single file
    that has the most of them, not one.
    """
    by_key: dict[tuple, dict[str, list[Transaction]]] = defaultdict(lambda: defaultdict(list))
    for t in transactions:
        by_key[_key(t)][t.file].append(t)

    keep: set[int] = set()
    for per_file in by_key.values():
        keep.update(id(t) for t in max(per_file.values(), key=len))
    kept = [t for t in transactions if id(t) in keep]
    return kept, len(transactions) - len(kept)


@dataclass
class TransferMatch:
    out: Transaction
    into: Transaction


def match_transfers(transactions: list[Transaction], window_days: int) -> list[TransferMatch]:
    """Pair money leaving one of your accounts with the same amount arriving
    in another within `window_days`, and mark both sides internal so the
    move is not counted as spending and income.

    At least one side must be a row a parser knows is your own money moving:
    an RM50 dinner and RM50 from a friend the next day aren't a transfer.

    Rows the parsers know are transfers are paired with each other first;
    only then may an ordinary row (a card charge that reloaded a wallet) take
    a leftover partner. Otherwise a RM6.30 Grab ride could take the partner
    of a RM6.30 transfer made the same day.
    """
    used: set[int] = set()
    matches = []
    known = [t for t in transactions if t.transfer]
    _pair(known, window_days, used, matches)
    # Splitwise rows are money between you and friends, never your own accounts.
    open_ = [t for t in transactions if (not t.internal or t.transfer) and t.source != "Splitwise"]
    _pair(open_, window_days, used, matches)
    return matches


def _pair(pool: list[Transaction], window_days: int, used: set[int], matches: list[TransferMatch]) -> None:
    outs = sorted((t for t in pool if t.amount < 0 and id(t) not in used), key=lambda t: t.date)
    ins: dict[float, list[Transaction]] = defaultdict(list)
    for t in pool:
        if t.amount > 0:
            ins[round(t.amount, 2)].append(t)

    for out in outs:
        best = None
        for candidate in ins[round(-out.amount, 2)]:
            if id(candidate) in used or not (out.transfer or candidate.transfer):
                continue
            if (candidate.source, candidate.account) == (out.source, out.account):
                continue
            gap = abs((candidate.date - out.date).days)
            if gap > window_days:
                continue
            if best is None or gap < abs((best.date - out.date).days):
                best = candidate
        if best is None:
            continue
        used.update((id(best), id(out)))
        out.internal = best.internal = True
        out.note = _join(out.note, f"transfer to {best.source} {best.account}")
        best.note = _join(best.note, f"transfer from {out.source} {out.account}")
        matches.append(TransferMatch(out, best))


def _join(a: str, b: str) -> str:
    return f"{a}; {b}" if a else b


def sort_ledger(transactions: list[Transaction]) -> list[Transaction]:
    return sorted(transactions, key=lambda t: (t.date, t.source, t.account))


# ---- Splitwise rows that are also on a statement ------------------------------------

SPLITWISE = "Splitwise"
SPLITWISE_DAYS = 4  # a card charge abroad can post a few days after the Splitwise date
CLOSE = 0.03  # a converted amount this close to one bank row is taken as the same
LOOSE = 0.08  # ... and this close only asks you


@dataclass
class SplitwiseMatch:
    splitwise: Transaction
    bank: Transaction
    sure: bool


def _foreign(t: Transaction) -> bool:
    """Splitwise rows keep the group's currency in the description ("Dinner · JPY 12,000.00")."""
    m = re.search(r" · ([A-Z]{3}) [\d,]+\.\d\d$", t.description)
    return bool(m) and m.group(1) != "MYR"


def match_splitwise(transactions: list[Transaction]) -> list[SplitwiseMatch]:
    """Splitwise rows that are the same money as a bank or wallet row: what
    you paid by card and also put in Splitwise, or a repayment that shows
    as a transfer. Same direction, within SPLITWISE_DAYS.

    The same RM amount is a match (nearest date first). A row in another
    currency, converted at the trip's rate, never matches the card's RM
    exactly: one bank row within CLOSE is a match; otherwise the nearest
    within LOOSE is only a maybe (`sure` False). Run after transfer
    pairing, so money between your own accounts is never taken."""
    sw = sorted((t for t in transactions if t.source == SPLITWISE and t.amount and not t.internal), key=lambda t: t.date)
    banks = [t for t in transactions if t.source != SPLITWISE and t.amount and not t.internal]
    used: set[int] = set()
    out: list[SplitwiseMatch] = []

    def candidates(s: Transaction) -> list[Transaction]:
        return [b for b in banks if id(b) not in used and (b.amount > 0) == (s.amount > 0)
                and abs((b.date - s.date).days) <= SPLITWISE_DAYS]

    def take(s: Transaction, b: Transaction, sure: bool) -> None:
        used.update((id(s), id(b)))
        out.append(SplitwiseMatch(s, b, sure))

    for s in sw:  # exact amounts first, so a converted row can't take an exact row's partner
        exact = [b for b in candidates(s) if abs(abs(b.amount) - abs(s.amount)) < 0.005]
        if exact:
            take(s, min(exact, key=lambda b: abs((b.date - s.date).days)), True)
    for s in sw:
        if id(s) in used or not _foreign(s):
            continue
        off = {id(b): abs(abs(b.amount) - abs(s.amount)) / abs(s.amount) for b in candidates(s)}
        near = sorted((b for b in candidates(s) if off[id(b)] <= LOOSE), key=lambda b: off[id(b)])
        if near:
            close = [b for b in near if off[id(b)] <= CLOSE]
            take(s, near[0], len(close) == 1)
    return out

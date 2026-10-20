from __future__ import annotations

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

    Matching is by amount and date only, so review the Transfers sheet.

    Rows the parsers already know are transfers are paired with each other
    first; only then may an ordinary row (a card charge that reloaded a
    wallet) take a leftover partner. Otherwise a RM6.30 Grab ride could take
    the partner of a RM6.30 transfer made the same day.
    """
    used: set[int] = set()
    matches = []
    known = [t for t in transactions if t.transfer]
    _pair(known, known, window_days, used, matches)
    # Splitwise rows are money between you and friends, never your own accounts.
    open_ = [t for t in transactions if (not t.internal or t.transfer) and t.source != "Splitwise"]
    _pair(open_, open_, window_days, used, matches)
    return matches


def _pair(
    out_pool: list[Transaction], in_pool: list[Transaction], window_days: int,
    used: set[int], matches: list[TransferMatch],
) -> None:
    outs = sorted((t for t in out_pool if t.amount < 0 and id(t) not in used), key=lambda t: t.date)
    ins = [t for t in in_pool if t.amount > 0]

    for out in outs:
        best = None
        for candidate in ins:
            if id(candidate) in used:
                continue
            if (candidate.source, candidate.account) == (out.source, out.account):
                continue
            if round(candidate.amount, 2) != round(-out.amount, 2):
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

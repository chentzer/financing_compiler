"""Cards for the recorded transactions that still need something from you:
what it was for (the Item is only "Transfer"/"QR payment") and/or a
Category.

Everything is recorded first; this runs right after, one card at a time.
Enter leaves a card for later. It stays in the "To Update" tab and comes
back on the next run. Answers are saved in answers.json (outside the repo),
keyed by the row key, after every card, so stopping halfway keeps your work.
The next upload writes them into the rows already in Google Sheets.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .accounts import AccountRow
from .config import Config

NEED_LABELS = {"purpose": "what it was for", "category": "Category"}
WIDTH = 66


def load_answers(path: Path) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_answers(path: Path, answers: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answers, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def card(row: AccountRow, n: int, total: int) -> str:
    sign = "+" if row.kind == "earn" else "-"
    needs = ", ".join(NEED_LABELS[x] for x in row.needs)
    lines = [
        f"{n} of {total}".ljust(WIDTH - len(f"needs: {needs}")) + f"needs: {needs}",
        f"{row.date:%d %b %Y}   {sign}RM {row.amount:,.2f}   {row.source}",
        row.remarks,
        f"Statement: {row.statement}",
        f"Recorded as: {row.item}" + (f"  ({row.category})" if row.category else ""),
    ]
    border = "+" + "-" * (WIDTH + 2) + "+"
    body = []
    for line in lines:
        while len(line) > WIDTH:
            body.append(line[:WIDTH])
            line = "  " + line[WIDTH:]
        body.append(line)
    return "\n".join([border, *(f"| {l.ljust(WIDTH)} |" for l in body), border])


def _pick(ask: Callable[[str], str], label: str, options: list[str], first: bool) -> str | None:
    """A choice by number or the first letters. None = later/stop/skip
    signalled by the caller via the special replies."""
    menu = "  ".join(f"{i}) {o}" for i, o in enumerate(options, start=1))
    while True:
        raw = ask(f"  {label} [{menu}]{' (Enter = later)' if first else ' (Enter = blank)'}: ").strip()
        if not raw or (first and raw.lower() in ("s", "q")):
            return raw.lower()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        matches = [o for o in options if o.lower().startswith(raw.lower())]
        if len(matches) == 1:
            return matches[0]


def update_cards(
    rows: list[AccountRow],
    config: Config,
    answers: dict[str, dict],
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> int:
    """Show each row's card and take your update. Returns how many you
    answered; the rest stay for later."""
    say("At any question: Enter = come back to it later, s = not mine (remove it), q = stop.\n")
    done = 0
    for n, row in enumerate(rows, start=1):
        say(card(row, n, len(rows)))
        answer: dict = {"date": str(row.date), "amount": row.amount, "statement": row.statement}
        try:
            if "purpose" in row.needs:
                first = ask("  What was it for? ").strip()
            else:
                first = _pick(ask, "Category", config.categories, first=True)
        except (EOFError, KeyboardInterrupt):
            break
        if first in ("q", "Q"):
            break
        if not first:
            say("  Left for later.\n")
            continue
        if first.lower() == "s":
            answer["skip"] = True
        else:
            if "purpose" in row.needs:
                answer["item"] = first
                if row.kind == "spend":
                    answer["category"] = _pick(ask, "Category", config.categories, first=False) or ""
            else:
                answer["category"] = first
            if row.kind == "spend":
                answer["importance"] = _pick(ask, "Importance", config.importance, first=False) or ""
            _offer_rule(row, answer, answers, ask)
        answer.update(reviewed=True, synced=False)
        answers[row.key] = answer
        save_answers(config.answers, answers)
        done += 1
        say("")
    return done


def _offer_rule(row: AccountRow, answer: dict, answers: dict, ask: Callable[[str], str]) -> None:
    """Regulars (a shop you go to, AIA's monthly RM10): answer once."""
    who = row.counterparty or row.statement
    what = answer.get("item") or answer.get("category")
    if not who or not what:
        return
    direction = {"earn": "from", "spend": "to"}[row.kind] if row.counterparty else "at"
    again = ask(f"  Same for every payment {direction} {who} from now on? [y/N] ")
    if not again.strip().lower().startswith("y"):
        return
    rule = {"match": who}
    for key in ("item", "category", "importance"):
        if answer.get(key):
            rule[key] = answer[key]
    answers.setdefault("_rules", []).append(rule)

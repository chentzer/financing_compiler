"""Statements in, accounts out: the steps the web app runs.

Works on bytes only (no files, no network), so it runs unchanged in the
browser under Pyodide.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .accounts import AccountRow, Tab, build_rows, plan
from .combine import TransferMatch, dedupe, match_transfers, sort_ledger
from .config import Config
from .models import Transaction
from .parsers import ParseError, PasswordNeeded, build_parsers, find_parser


@dataclass
class FileResult:
    name: str
    source: str = ""  # which bank, when recognised
    parser: str = ""  # parser key, e.g. "tng": which saved password it used
    count: int = 0
    error: str = ""
    needs_password: str = ""  # parser name, when the PDF is locked

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class Compiled:
    transactions: list[Transaction]
    matches: list[TransferMatch]
    rows: list[AccountRow]
    tabs: dict[int, list[Tab]]
    files: list[FileResult] = field(default_factory=list)
    duplicates: int = 0
    # The new statements' transactions exactly as parsed (before pairing
    # marks some internal): what gets stored, so pairing can be redone.
    parsed: list[Transaction] = field(default_factory=list)


def parse_files(files: list[tuple[str, bytes]], config: Config) -> tuple[list[Transaction], list[FileResult]]:
    parsers = build_parsers(config)
    transactions: list[Transaction] = []
    results = []
    for name, data in files:
        parser = find_parser(name, data, parsers)
        if parser is None:
            results.append(FileResult(name, error="not a statement fincomp recognises"))
            continue
        try:
            found = parser.parse_bytes(name, data, config.password(parser.name))
        except PasswordNeeded as e:
            results.append(FileResult(name, parser.label, parser.name, error=str(e), needs_password=e.parser))
            continue
        except ParseError as e:
            results.append(FileResult(name, parser.label, parser.name, error=str(e)))
            continue
        results.append(FileResult(name, parser.label, parser.name, count=len(found)))
        transactions.extend(found)
    return transactions, results


def compile_statements(
    files: list[tuple[str, bytes]],
    config: Config,
    answers: dict[str, dict] | None = None,
    earlier: list[Transaction] | None = None,
    match: bool = True,
) -> Compiled:
    """Parse `files` and combine them with the transactions of statements
    uploaded `earlier`, so dedupe and transfer pairing see every bank."""
    new, results = parse_files(files, config)
    parsed = [replace(t) for t in new]
    combined = [replace(t) for t in keep_earlier(earlier or [], new)] + new
    compiled = compile_transactions(combined, config, answers, match=match, files=results)
    compiled.parsed = parsed
    return compiled


def keep_earlier(earlier: list[Transaction], new: list[Transaction]) -> list[Transaction]:
    """The earlier uploads' rows a new upload doesn't replace. A statement
    uploaded again replaces its earlier copy: same file name and bank, dated
    within what the new file covers. A same-named statement from another
    month or bank, or a file that couldn't be read, replaces nothing."""
    spans: dict[tuple[str, str], tuple] = {}
    for t in new:
        lo, hi = spans.get((t.file, t.source), (t.date, t.date))
        spans[(t.file, t.source)] = (min(lo, t.date), max(hi, t.date))

    def replaced(t: Transaction) -> bool:
        span = spans.get((t.file, t.source))
        return span is not None and span[0] <= t.date <= span[1]

    return [t for t in earlier if not replaced(t)]


def compile_transactions(
    transactions: list[Transaction],
    config: Config,
    answers: dict[str, dict] | None = None,
    match: bool = True,
    files: list[FileResult] | None = None,
) -> Compiled:
    transactions, dupes = dedupe(transactions)
    matches = match_transfers(transactions, config.transfer_window_days) if match else []
    transactions = sort_ledger(transactions)
    rows = build_rows(transactions, config, answers or {})
    return Compiled(transactions, matches, rows, plan(rows, config), files or [], dupes)

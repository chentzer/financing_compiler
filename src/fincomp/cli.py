from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .accounts import build_rows, needs_update, plan
from .accounts_xlsx import write_accounts_xlsx
from .config import load_config
from .export import write_csv, write_excel
from .gsheets import UploadError, upload
from .pipeline import compile_statements
from .review import load_answers, save_answers, update_cards


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="fincomp", description="Combine bank and e-wallet statements into one ledger."
    )
    ap.add_argument("-i", "--input", type=Path, default=Path("statements"), help="folder of statements")
    ap.add_argument("-o", "--output", type=Path, default=Path("output"), help="folder for the result")
    ap.add_argument("-c", "--config", type=Path, default=Path("config.toml"))
    ap.add_argument("--transfer-window", type=int, help="days; overrides transfer_window_days")
    ap.add_argument("--no-transfers", action="store_true", help="don't match transfers between accounts")
    ap.add_argument("--csv", action="store_true", help="also write a flat CSV of all transactions")
    ap.add_argument("--upload", action="store_true", help="upload the monthly accounts to Google Sheets")
    ap.add_argument(
        "--push-settings", action="store_true",
        help="one-time: copy rules, people, trips, passwords and parsed statements to Drive for the app",
    )
    ap.add_argument(
        "--no-review", action="store_true",
        help="don't go through the To Update cards after this run (they wait in the To Update tab)",
    )
    args = ap.parse_args(argv)

    config = load_config(args.config)
    if args.transfer_window is not None:
        config.transfer_window_days = args.transfer_window

    paths = sorted(p for p in args.input.rglob("*") if p.is_file() and not p.name.startswith("."))
    if not paths:
        print(f"No statements in {args.input}/. Put your PDFs or CSVs there.")
        return 1

    answers = load_answers(config.answers)
    compiled = compile_statements(
        [(p.name, p.read_bytes()) for p in paths], config, answers, match=not args.no_transfers
    )
    failed = 0
    for f in compiled.files:
        if f.ok:
            print(f"  ok     {f.name}: {f.count} transactions ({f.source})")
        elif not f.source:
            print(f"  skip   {f.name}: no parser recognises this file")
        else:
            print(f"  FAIL   {f.error}")
            failed += 1
    transactions, matches = compiled.transactions, compiled.matches
    if not transactions:
        print("Nothing parsed.")
        return 1
    if args.push_settings:
        from .gsheets import push_settings

        from getpass import getpass

        from .vault import WrongPin

        def ask_pin(creating: bool) -> str:
            if not creating:
                return getpass("PIN for your saved statement passwords: ")
            while True:
                pin = getpass("Create a PIN to encrypt your statement passwords (6+ characters): ")
                if len(pin) >= 6 and pin == getpass("Type it again: "):
                    return pin
                print("  They didn't match, or it's shorter than 6 characters. Try again.")

        try:
            url = push_settings(config, ask_pin, ledger=compiled.parsed)
        except (UploadError, WrongPin) as e:
            print(f"  FAIL   push-settings: {e}")
            return 3
        print(f"Settings, encrypted passwords and {len(compiled.parsed)} transactions are in your Drive: {url}")
        return 0
    if compiled.duplicates:
        print(f"Dropped {compiled.duplicates} duplicate rows from overlapping statements.")
    if matches:
        print(f"Matched {len(matches)} transfers between your accounts (see the Transfers sheet).")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.output / f"combined_{stamp}.xlsx"
    write_excel(out, transactions, matches)
    print(f"Wrote {len(transactions)} transactions to {out}")
    if args.csv:
        write_csv(out.with_suffix(".csv"), transactions)

    # Everything is recorded; then you're shown what still needs you.
    rows = compiled.rows
    todo = needs_update(rows)
    if todo and not args.no_review and sys.stdin.isatty():
        go = input(f"\n{len(todo)} recorded transaction(s) need updating. Go through them now? [Y/n] ")
        if not go.strip().lower().startswith("n"):
            update_cards(todo, config, answers)
            rows = build_rows(transactions, config, answers)
            todo = needs_update(rows)
    if todo:
        print(f"{len(todo)} transaction(s) still need updating. They're in the 'To Update' tab; "
              "run fincomp again to go through them, or edit them in the month tabs.")

    tabs = plan(rows, config)
    for path in write_accounts_xlsx(args.output, tabs, config):
        print(f"Wrote accounts in your template layout to {path}")

    if args.upload or config.google.upload:
        try:
            for r in upload(tabs, config, answers):
                print(f"Uploaded to '{r.title}': {r.added} new rows, {r.already} already there. {r.url}")
                if r.fixed_in_sheet:
                    print(f"  {r.fixed_in_sheet} card(s) closed because you'd already fixed them in the sheet.")
                if r.to_update:
                    print(f"  {r.to_update} card(s) still open in its 'To Update' tab.")
        except UploadError as e:
            print(f"  FAIL   upload: {e}")
            return 3
        finally:
            save_answers(config.answers, answers)  # remembers which answers are now in the sheet

    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

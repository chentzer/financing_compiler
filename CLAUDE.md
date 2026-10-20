# financing_compiler (the app is called **FinMerge**)

The app's name is FinMerge everywhere the user sees it (site title,
header, Android app name). Code, the Python package/CLI (`fincomp`), the
Android package id `com.chentzer.fincomp`, and the Drive file names
("fincomp Settings", the fincomp folder) keep the old name on purpose:
renaming those would lose the user's data or the Google sign-in setup.

`fincomp` reads statements from several Malaysian banks and e-wallets and
writes monthly accounts to the user's Google Sheets. It runs two ways from
one Python package:

- **Website + Android app** (`web/`): no server. The page runs `fincomp`
  in the browser with Pyodide, parses PDFs on the device, and calls the
  Google Sheets/Drive APIs directly with the user's Google sign-in. It's
  deployed to GitHub Pages; Android is the same app wrapped by Capacitor,
  built and signed by `.github/workflows/android.yml` (APK on the
  `android` release). The signing key is in the gitignored `.signing/`:
  never commit it.
- **CLI** (`python -m fincomp`) for development and the one-time
  `--push-settings`.

Started from a friend's TNG/Maybank scripts (a fork of
Rexpert/TNG_Statement_in_CSV, MIT), rewritten as one tool with a parser per
source.

**The repo is public.** Read "Privacy" below before adding anything.

## Run

```
python -m venv .venv
.venv/Scripts/pip install -e ".[tng,google,dev]"
.venv/Scripts/python -m fincomp            # reads statements/, writes output/
.venv/Scripts/python -m pytest
```

## Layout

- `models.py`: `Transaction`, the common schema every parser emits.
- `parsers/`: one module per source, bytes in (`parse_bytes`), registered
  in `parsers/__init__.py`. PDF parsers use only `pypdf` + `re`
  (`TextPdfParser`), so they run in a browser. TNG v1 is rebuilt from text
  positions. Only TNG v2 (camelot) and CSV (pandas) are CLI-only, and they
  import those lazily. `splitwise.py` reads a Splitwise group export (stdlib
  csv): what the user paid = spending, repayments to them = earnings,
  converted at the trip's rate; never paired as transfers.
- `pipeline.py`: statements → parsed → dedupe → transfer pairing → account
  rows → tabs. Used by both the CLI and the web app.
- `combine.py`: dedupe overlapping statements, pair transfers between the
  user's own accounts.
- `accounts.py`: the monthly accounts layout from the user's
  `Account Template.xlsx` (cell positions, SUMIF summaries, rules, row
  keys, To Update cards).
- `sheetplan.py`: **pure** plans of what to read and write in a yearly
  spreadsheet (no HTTP). `gsheets.py` runs them with gspread (CLI); the web
  app runs them with fetch().
- `settings.py`: the "fincomp Settings" sheet (Rules, People, Trips, Own
  payees, Lists, Sheets, Removed, Reviewed, hidden Ledger) ↔ `Config`. Passwords are in the
  Drive App Data folder, never in a sheet.
- `suggest.py`: category suggestions for To Update cards (your past rows,
  then common shop words). Categories are the user's list (Settings ›
  Lists); adding one rewrites month tabs' By Category block and dropdowns
  (`sheetplan.category_refresh`).
- `custom.py`: custom sheets (app's Sheets section): tabs of tables
  (Date | <label> | Amount (<currency>) | Remarks | key), 6 columns each,
  listed in Settings › Sheets; RM tables of a sheet that counts as
  earnings/spending feed the Year End Summary. Managed by fincomp once listed.
- `old_accounts.py`: an accounts workbook the user kept by hand (template
  layout, .xlsx; zipfile + xml, no openpyxl) copied into the new layout as
  hand-added rows with content-based "m-" keys, so re-importing adds nothing.
  Trip tabs (2023 "Japan Trip" layout) become a trip in Settings plus all
  three blocks; other table tabs (ang pao) become custom sheets.
- `webapi.py`: the JSON-in/JSON-out functions the web app calls through
  Pyodide.
- `accounts_xlsx.py`, `export.py`, `review.py`, `cli.py`: CLI only.

Keep `webapi.py`'s import tree free of pandas, numpy, camelot, openpyxl and
gspread (Pyodide check: see README).

## Accounts layout rules

- Positions (column constants in accounts.py; the user changed them in
  Oct 2026): Spendings A-G (Date, Item, Category, Amount, Importance,
  Source, Remarks), Category summary J-K, Importance summary M-N, Earnings
  P-T (Date, Item, Amount, Source, Remarks), summary W-X with Final in X6.
  Hidden keys in H and U; blank columns I, L, O, V. Section headers are
  coloured. Source = bank/wallet; Remarks starts as the statement text.
- Trip tabs: RM spending A-G (key in H), spending in the trip currency J-O
  and money received T-W (no keys; the app can append to J-O), summary Q-R
  with the trip total in R8. Month X5 = trips ending that month, Final (X6)
  subtracts it.
- Older tabs are converted by inserting columns (sheetplan.upgrade_*), never
  by rewriting rows. Rows the app adds by hand get "m-..." keys.
- Never reorder or write to tabs fincomp doesn't manage; insert new tabs
  before the next managed tab in date order.
- Sheets sync is append-only except for the user's own answers and edits:
  only the answered cells of rows that already have a key are written;
  rows without a key were typed by hand and are never touched. "Not mine"
  removes the row from its block and adds its key to Settings › Removed so
  it never comes back.

## Recording rules (from the user; apply to every parser)

1. Ignore money moving between the user's own accounts, at the same bank
   or different banks/wallets (mark `internal`; `transfer` too when the
   other side may be in another statement).
2. Record only the user's own spending, and money coming in from someone
   else (family included).
3. Everything that isn't excluded is recorded: Item = the purpose when the
   statement gives one, otherwise the shop name or "Transfer"/"QR
   payment"; Source = bank/wallet; Remarks = the statement text (the
   "To <name>"/"From <name>" text is on the To Update card); Category from rules or
   blank. Never hold rows back. Rows missing a purpose and/or Category get
   a To Update card, shown one at a time right after an upload; skipped
   cards stay in the "To Update" tab. Editing the month tab directly closes
   a card.

Per-bank behaviour is documented at the top of each parser. Transfer
matching pairs parser-flagged transfers with each other before ordinary
rows, so a same-amount purchase can't take a transfer's partner.

## Privacy (public repo)

- Never commit statements, output, `config.toml` (passwords),
  `privacy_denylist.txt`, or `NOTES.local.md`. Never hardcode a password.
- Tests, docs and examples use **made-up** names, numbers and notes only
  (Jane Tan, Bob Lim, Tan Mei Ling…), never anything copied from a real
  statement. `tests/test_privacy.py` fails if any term in the local
  `privacy_denylist.txt` appears in a file git would publish. Add new real
  names to that list whenever a new statement comes in.
- The user's own context (which real people/accounts are which) is in the
  gitignored `NOTES.local.md`.
- Ask before every push to GitHub.
- Commits here use the GitHub noreply address
  (`109493984+chentzer@users.noreply.github.com`, set in this repo's git
  config), not the personal email: the repo is public.

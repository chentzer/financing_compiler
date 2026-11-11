# financing_compiler (the app is called **FinMerge**)

The app's name is FinMerge everywhere the user sees it (site title,
header, Android app name). Code, the Python package (`fincomp`), the
Android package id `com.chentzer.fincomp`, and the Drive file names
("fincomp Settings", the fincomp folder) keep the old name on purpose:
renaming those would lose the user's data or the Google sign-in setup.

`fincomp` reads statements from several Malaysian banks and e-wallets and
writes monthly accounts to the user's Google Sheets. There are only two ways
to use it, from one Python package (the command-line tool was deleted on
purpose):

- **Website + Android app** (`web/`): no server. The page runs `fincomp`
  in the browser with Pyodide, parses PDFs on the device, and calls the
  Google Sheets/Drive APIs directly with the user's Google sign-in. It's
  deployed to GitHub Pages; Android is the same app wrapped by Capacitor,
  built and signed by `.github/workflows/android.yml` (APK on the
  `android` release). The signing key is in the gitignored `.signing/`:
  never commit it.

Started from a friend's TNG/Maybank scripts (a fork of
Rexpert/TNG_Statement_in_CSV, MIT), rewritten as one tool with a parser per
source.

**The repo is public.** Read "Privacy" below before adding anything.

## Run

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m pytest
cd web; npm install; npm run dev           # demo data at localhost:5173
```

## Layout

- `models.py`: `Transaction`, the common schema every parser emits.
- `parsers/`: one module per source, bytes in (`parse_bytes`), registered
  in `parsers/__init__.py`. PDF parsers use only `pypdf` + `re`
  (`TextPdfParser`), so they run in a browser. TNG v1 is rebuilt from text
  positions; the older TNG v2 layout is refused. `splitwise.py` reads a Splitwise group export (stdlib
  csv): what the user paid = spending, repayments to them = earnings,
  converted at the trip's rate; never paired as transfers. A Splitwise row
  that is also on a statement is recorded once (`combine.match_splitwise`,
  `pipeline.settle_splitwise`): the side uploaded later goes to Settings ›
  Removed; maybes and pairs already in the sheet get a "same as?" card
  (Different = Reviewed row "splitwise key~bank key").
- `pipeline.py`: statements → parsed → dedupe → transfer pairing → account
  rows → tabs.
- `combine.py`: dedupe overlapping statements, pair transfers between the
  user's own accounts.
- `accounts.py`: the monthly accounts layout from the user's
  `Account Template.xlsx` (cell positions, SUMIF summaries, rules, row
  keys, To Update cards).
- `sheetplan.py`: **pure** plans of what to read and write in a yearly
  spreadsheet (no HTTP); the web app runs them with fetch().
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
  Each has a category: the app groups Sheets by it, and "Investments" ones
  get their own tab. Sheet and trip names are unique across years (an
  import from another year adds the year to a clashing name).
- `old_accounts.py`: an accounts workbook the user kept by hand (template
  layout, .xlsx; zipfile + xml, no openpyxl) copied into the new layout as
  hand-added rows with content-based "m-" keys, so re-importing adds nothing.
  Trip tabs (2023 "Japan Trip" layout) become a trip in Settings plus all
  three blocks; other table tabs (ang pao) become custom sheets.
- `overview.py`: what Home (this year's and to-date totals, from each
  month's summary cells and the Year End Summary) and the Trips screen
  (one trip tab's blocks) read back.
- `webapi.py`: the JSON-in/JSON-out functions the web app calls through
  Pyodide.

Everything under `src/fincomp` ships to the browser: keep it free of pandas,
numpy, camelot, openpyxl and gspread.

## Accounts layout rules

- Positions (column constants in accounts.py; the user changed them in
  Oct 2026): Spendings A-G (Date, Item, Category, Amount, Importance,
  Source, Remarks), Category summary J-K, Importance summary M-N, Earnings
  P-T (Date, Item, Amount, Source, Remarks), summary W-X with Final in X6.
  Hidden keys in H and U; blank columns I, L, O, V. Section headers are
  coloured. Source = bank/wallet; Remarks starts as the statement text.
- Trip tabs (the user's 2025 trip sheets): RM spending A-G (key in H), paid
  back to you (RM) J-M (key in N), summary P-Q with the trip total in Q4 =
  RM spent + each currency x its rate - paid back; then one spending block
  per currency from S (Trip.currency + Trip.extra, each with its rate), then
  money received in other currencies. Month X5 = trips ending that month,
  Final (X6) subtracts it. Trips are added and changed on the Trips screen,
  not in Settings. Rows the app adds by hand get "m-..." keys.
- Never reorder or write to tabs fincomp doesn't manage; insert new tabs
  before the next managed tab in date order.
- Sheets sync is append-only except for the user's own answers and edits:
  only the answered cells of rows that already have a key are written;
  rows without a key were typed by hand and are never touched. "Not mine"
  removes the row from its block and adds its key to Settings › Removed so
  it never comes back.

## App UI rules (from the user; check every screen change against them)

The app is used mostly on an Android phone. Before calling UI work done,
check it at 375px wide, in light and dark, and at 200% text size.

1. **Platform guides.** Follow Material Design (Android) and Apple's HIG
   (iOS). Matching how the platform already behaves means less to learn.
2. **Navigation.** 3-5 bottom tabs for the top-level sections (now: Home,
   Accounts, Upload, To Update, Sheets). A hub's own pages are sub-tabs
   across its top, all visible, never hidden behind "More". Tabs only
   navigate: an action (add, save, upload now) is a button on the screen,
   never a tab. Rarely used places (Settings) go in the header, not the
   bar. Desktop (900px+) uses the side nav with every page listed.
3. **Touch targets.** Every tappable thing is at least 48x48 px on phones
   (Android 48dp; Apple 44pt). The icon or text can be smaller: padding
   makes up the rest. Never below 24x24 (WCAG 2.2). This includes text
   links, table links, chips and sub-tabs.
4. **Accessibility (WCAG 2.2 AA).** Contrast 4.5:1 for normal text, 3:1
   for large text, and 3:1 for whatever shows a control is there (input
   and chip outlines, switch tracks, focus rings), in both themes. Check
   new colours with a contrast calculation, not by eye. No orientation
   lock.
5. **Large text.** Nothing assumes a fixed font size: at 200% text the page
   must not scroll sideways, the bottom bar must still show every tab, and
   text wraps instead of being cut. Use rem/em and min-height, not fixed
   pixel heights, for anything holding text.
6. **Performance (Android vitals).** Cold start under 5 s, warm under 2 s,
   hot under 1.5 s. Show something useful before Python and Google calls
   finish; never block the first screen on work only uploads need. No
   crashes or frozen screens: long work runs in the background with
   progress.
7. **UX (Shneiderman).** Feedback for every action (a toast, progress or
   a changed screen). Undo is easy: prefer an "Undo" on the toast over
   an "are you sure?" step for anything that can be reversed. Prevent
   errors (disable Save until valid; say what's wrong next to the field).
   Don't make the user remember things between screens. Keep screens
   simple and split long forms into steps.
8. **Saved state.** Coming back to a tab restores its scroll position,
   filters, chosen month/year and sub-tab, and any half-done work (e.g.
   an upload in progress).
9. **First-launch tour** (`web/src/components/Tour.tsx`). Runs once per
   device after sign-in, spotlights the real control (`data-tour="..."`
   on it) with one sentence per step, "3 of N" progress and Next / Back
   / Skip; replay from Settings. When a tab or feature is added, moved or
   removed, update `STEPS` (and its `data-tour` markers) in the same
   change: a feature isn't done until the tour covers it. Check it at
   375px and at 200% text: no card covers its spotlight or leaves the
   screen.

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


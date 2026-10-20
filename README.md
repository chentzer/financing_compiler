# financing_compiler

Turns Malaysian bank and e-wallet statements (AEON Bank, AEON Credit, GX,
Maybank, Ryt, Touch 'n Go) into monthly accounts in your own Google Sheets.

- **Website**: https://chentzer.github.io/financing_compiler/, and an
  **Android app** built from the same code. Pick your statement PDFs, and
  they're read **on your device**. The results go straight to your Google
  Drive. There's no server: nothing is sent anywhere except your own Drive.
- **Command line** (below), for development.

## How the website works

1. Sign in with Google. The app can only see files it created itself, plus
   its own hidden App Data folder.
2. **Upload** statement PDFs. The `fincomp` Python package runs in your
   browser ([Pyodide](https://pyodide.org)). It reads the PDFs, drops money
   moving between your own accounts, pairs transfers across banks, and
   applies your rules.
3. The results go into **"2026 Accounts"** (one spreadsheet per year): month
   tabs, trip tabs, a **To Update** tab and a Year End Summary.
4. The **To Update** cards come up one at a time: what each transaction was
   for, its Category and Importance. Choose Save, Later or Not mine.

Also in your Drive:

- **"fincomp Settings"**: Rules, People, Trips, Own payees and Lists.
  You can edit them in the app or in Sheets. It also holds a hidden Ledger
  of everything uploaded, so statements can come in one at a time.
- **Statement passwords**, saved in the app's private App Data folder,
  which other apps can't open and isn't shown in your Drive file list.

The PDFs themselves are not kept: they're read on your device and
discarded once the upload is done. Only the transactions read from them
are saved (in the Ledger above).

### One-time Google setup (for whoever runs the site)

1. In <https://console.cloud.google.com/>, create a project. No billing is
   needed.
2. **APIs & Services › Library**: enable **Google Sheets API** and **Google
   Drive API**.
3. **Google Auth Platform / OAuth consent screen**: External. Add your
   Google account under **Audience › Test users**. Scopes: `spreadsheets`,
   `drive.file`, `drive.appdata`.
4. **Credentials › Create credentials › OAuth client ID › Web
   application**. Authorised JavaScript origins:
   `https://chentzer.github.io` and `http://localhost:5173`.
5. On GitHub: repo **Settings › Secrets and variables › Actions ›
   Variables**. Add `GOOGLE_CLIENT_ID` (the Web client ID). Optionally add
   `ALLOWED_EMAILS` (comma-separated) to lock the site to those accounts.
   Until `GOOGLE_CLIENT_ID` is set, the site runs in demo mode with
   made-up data.
6. Optional, to bring over what's in your local `config.toml` (rules,
   people, trips, passwords) and the statements in `statements/`: create a
   **Desktop** OAuth client too, save its JSON as
   `~/.config/fincomp/credentials.json`, and run
   `python -m fincomp --push-settings`.

### Developing the website

```
cd web
npm install
npm run dev        # demo data; set VITE_BACKEND=real + VITE_GOOGLE_CLIENT_ID in web/.env.local for Google
npm run build
```

`web/README.md` covers the app's code and the Android build. Every push
to `main` runs the Python tests, builds the site and deploys it to GitHub
Pages (`.github/workflows/pages.yml`).

## Command line

### Setup

```
python -m venv .venv
.venv/Scripts/pip install -e ".[tng,google]"
copy config.example.toml config.toml   # passwords, CSV formats, category rules
```

### Run

```
.venv/Scripts/python -m fincomp            # local files only
.venv/Scripts/python -m fincomp --upload   # and update the Google Sheet
```

Options: `-i <folder>`, `-o <folder>`, `-c <config>`, `--csv` (also write a
flat CSV), `--transfer-window N`, `--no-transfers`, `--upload`, `--no-review`.

## Supported sources

| Source | File | How it's recognised |
|---|---|---|
| AEON Bank (Savings Account-i + Savings pot) | PDF | `*Deposits-statement-*.pdf` |
| AEON Credit card | PDF, password in `passwords.aeon_credit` | `*e-statement*.pdf` that says AEON CREDIT SERVICE inside |
| GX Bank savings | PDF | `*-statement.pdf` that says GX Bank Berhad inside |
| Maybank savings (Maybank2u) | PDF | `M2U*.pdf` that says Malayan Banking Berhad inside |
| Ryt Bank (Main Account + pockets) | PDF | `Ryt_Bank*.pdf` |
| Touch 'n Go eWallet (wallet + GO+) | PDF (both layouts), password in `passwords.tng` | `*transactions*.pdf`, `tng*.pdf` |
| Maybank credit card | PDF | `<16-digit card no>_<YYYYMMDD>.pdf` |
| Any bank/wallet with a CSV or XLSX export | CSV/XLSX | a `[[csv]]` block in `config.toml` |

File-name patterns can be changed under `[patterns]` in `config.toml`.

TNG notes: reloads, GO+ cash in/out, and DuitNow to or from your own name
are your own money moving. "Transfer to Wallet" rows show only your note
("lunch"), so the note becomes the Item. GO+ pays
interest daily in fractions of a sen, so it's added up into one Earnings row
per month. Failed or reversed rows are ignored.

Ryt Bank notes: moves to and from your pockets ("Money movement") and
transfers to or from your own name are ignored. Card charges are dated by
the "Transaction date" in the row, and foreign currency and fees go in the
Note. Pockets only show up in the summary table, so their monthly interest
is added as one Earnings row on the last day of the statement.

Maybank savings notes: payments to anyone in `own_payees` (by default
AEON CREDIT SERVICE, i.e. paying your card bill) are your own money moving,
and they pair with the CR on the card statement. Add other card issuers or
investment accounts you pay into there.

AEON Credit notes: every **CR** row is ignored: payments to the card,
points redemption and cashback. Items are the merchant name with the city
and country removed ("AEON BIG-JAYA ONE PETALING JAYAMY" → "AEON BIG-JAYA
ONE"), dated by transaction date. The parsed charges are checked against the
statement's "Total charges" and "Closing balance".

AEON Bank notes: moves between your account and your Savings pot are
internal. So are DuitNow transfers to or from your own name, which the
parser reads from the statement. Those are your money moving to another bank
or wallet, and they're paired with the other side when that statement is
imported. Each row is checked against the running balance, so if AEON
changes the PDF layout the run stops instead of giving wrong totals.

## Output

- **All Transactions**: every row from every statement, oldest first.
  Amounts are positive for money in, negative for money out.
- **Money In / Money Out**: real income and spending, without internal moves.
- **Monthly Summary**: in, out and net per month and source.
- **Transfers**: money that moved between your own accounts (for example a
  card charge that reloaded your wallet). These are marked `Internal` so they
  aren't counted twice. They are matched only by amount and date (3 days
  by default), so check this sheet.

Statements that overlap (the same period exported twice) are deduplicated.

## What gets recorded

1. **Money between your own accounts is ignored**: savings pot moves, and
   transfers to or from your own name at another bank or wallet.
2. **Only your spending, and money in from other people, is recorded.**
3. **Everything else is recorded, and you fill in what the statement
   doesn't say.** If the statement gives a purpose, it becomes the Item:
   `TAN MEI LING - DuitNowID - lunch` becomes Item *Lunch*, Remarks *To Zai
   Yi*. If it doesn't (only "DuitNow QR" or a reference number), the row
   still goes in, as Item *Transfer* or *QR payment* with Remarks *From Yi
   Bei*, for you to edit in the sheet. Card charges use the shop name.
   Category and Importance come from `[[rules]]` in `config.toml`, or are
   left blank and add up under **Not set** in the month's summary.

## Updating what the statement didn't say

Right after every run, fincomp tells you how many recorded rows still need
something: what it was for, and/or a Category. It then offers to go through
them **one card at a time**:

```
18 recorded transaction(s) need updating. Go through them now? [Y/n]

+--------------------------------------------------------------------+
| 3 of 18                                     needs: what it was for |
| 05 Sep 2026   +RM 20.00   Ryt Bank                                 |
| From Jia Hao                                                       |
| Statement: From KOH JIA HAO - Transfer - Fund Transfer              |
| Recorded as: Transfer                                              |
+--------------------------------------------------------------------+
  What was it for?
```

- Type the answer (spending then asks Category and Importance, by number or
  first letters).
- **Enter**: come back to it later. **s**: not mine, remove it. **q**: stop for now.
- For a shop or person, it offers *"Same for every payment to … from now
  on?"*, so regulars are only asked once.

Every card you skip stays on the **To Update** tab, the first tab of the
workbook and of the Google Sheet, and comes back the next time you run
fincomp. You can also fix a row straight in the month tab. On the next
upload, fincomp sees that and closes its card.

Your answers are saved after each card in `~/.config/fincomp/answers.json`.
On the next `--upload` they're written into the rows already in the Google
Sheet, only the cells you answered. Rows you marked "not mine" are removed
from the Spendings or Earnings block.

`--no-review` skips the cards for one run. They wait in To Update.

Names in Remarks are shortened ("TAN MEI LING" → "Mei Ling"). To set a name
yourself, add it under `[people]` in `config.toml`.

## Monthly accounts (your template)

Each run also writes `output/<year> Accounts.xlsx` in the layout of
`Account Template.xlsx`, and `--upload` puts the same thing in a Google
Sheet named `<year> Accounts`:

- One tab per month (`July 2026`): **Spendings** in A–F (Date, Item,
  Category, Amount, Importance, Remarks), **Earnings** in N–Q.
- Spending by Category (H–I), by Importance (K–L), and Earnings / Spendings /
  **Final** in S–T. Final carries over from the previous month.
- A **Year End Summary** tab with total earnings, spending and the difference.
- Category and Importance have the template's dropdowns. `[[rules]]` in
  `config.toml` fills what it can, and the rest is left blank for you.
- Remarks shows which bank or wallet the row came from.
- Internal transfers (wallet reloads, card repayments, GO+ moves) are left out.

Differences from the old workbook: the summaries are SUMIF formulas, not
pivot tables. Pivot tables don't survive the move to Google Sheets and need
manual refreshing. Final always sits in T6, and the Year End Summary adds up
every month tab (the 2022 formula skipped some months).

### Trips

Declare a trip under `[[trips]]` in `config.toml` (name, dates, currency).
It gets its own tab, laid out like the 2023 "Japan Trip" sheet:

| Columns | What | Filled by |
|---|---|---|
| A–F | RM spending: flights, hotels, card charges abroad | fincomp, from statements |
| H–M | Cash spending in the trip currency | you |
| O–P | Spent in RM, Spent in Yen, rate, **Trip Total (RM)** in P8, Yen received / left (expected) / left (counted) / unaccounted | formulas, except "left (counted)" |
| Q–T | Yen received: money exchange, leftover from parents, friends paying back | you |

What goes to the trip tab: statement spending dated within the trip, plus
earlier bookings whose description matches the trip's `match` keywords, or
any `[[rules]]` entry with `trip = "<name>"`. Money coming in stays on the
month tab.

Name the RM row for buying currency **Money Exchange** (rename it in the
sheet; your edit is kept). It's left out of "Spent in RM" because that
money is counted when you spend the yen. If you don't set `rate`, the rate
is worked out from that row and the matching "Money Exchange" row in Q–T.

The trip tab goes right after the month the trip starts. The month it ends
shows the trip total under **Trips** (T5), and that month's Final subtracts
it. The Year End Summary counts trips in Total Spending.

Declare the trip **before** uploading statements from those dates. A row
already uploaded to a month tab isn't moved. To move it, delete it from the
month tab and run `--upload` again, and it will be added to the trip tab.

Tabs you make yourself, like "Chinese New Year", are never touched or moved.

**Re-running is safe.** Columns G and R are hidden and hold a key for each
uploaded row. A re-run only appends transactions that aren't in the sheet
yet, then sorts by date. Rows already there aren't rewritten, so Categories
you picked, items you renamed, and rows you typed in yourself (like cash
spending) are all kept.

## Google Sheets setup (one time)

fincomp signs in as you through a Google Cloud OAuth client that you own.
It asks only to create and edit spreadsheets **it made** (`drive.file`),
not the rest of your Drive.

1. Open <https://console.cloud.google.com/>, create a project (e.g. `fincomp`).
2. **APIs & Services → Library**: enable **Google Sheets API** and
   **Google Drive API**.
3. **Google Auth Platform / OAuth consent screen**: user type *External*.
   Fill in the app name and your email, and add your own Google account
   under **Audience → Test users**.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**.
   Download the JSON and save it as
   `C:\Users\<you>\.config\fincomp\credentials.json`.
5. Run `python -m fincomp --upload`. A browser opens: sign in, and on
   "Google hasn't verified this app" choose **Continue** (it's your own
   app). The token is saved next to `credentials.json`, outside the repo.

While the app is in *Testing* mode, Google expires the sign-in after 7 days.
fincomp then opens the browser again by itself. To avoid this, set the
consent screen's publishing status to *In production*. For a personal app
you don't need to go through verification.

To put the yearly spreadsheets in a particular Drive folder, set
`google.folder_id` to the folder's ID (the last part of its URL).

## Adding a bank

If it exports CSV, add a `[[csv]]` block. For PDF-only statements, add a
parser in `src/fincomp/parsers/` and register it in `parsers/__init__.py`.

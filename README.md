# FinMerge

(Repo `financing_compiler`; the Python package is `fincomp`.)

Turns Malaysian bank and e-wallet statements (AEON Bank, AEON Credit, GX,
Maybank, Ryt, Touch 'n Go) into monthly accounts in your own Google Sheets.

- **Website**: https://chentzer.github.io/financing_compiler/, and an
  **Android app** built from the same code. Pick your statement PDFs, and
  they're read **on your device**. The results go straight to your Google
  Drive. There's no server: nothing is sent anywhere except your own Drive.

## How the website works

1. Sign in with Google. The app can only see files it created itself, plus
   its own hidden App Data folder.
2. **Upload** statement PDFs. The `fincomp` Python package runs in your
   browser ([Pyodide](https://pyodide.org)). It reads the PDFs, drops money
   moving between your own accounts, pairs transfers across banks, and
   applies your rules. A checklist under it ticks off each of your banks
   once that month's statement is in.
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

The PDFs themselves are read on your device and discarded once the upload
is done; only the transactions read from them are saved (in the Ledger
above). Turn on "Keep a copy of each PDF" on the Upload screen to also keep
them in **Drive › fincomp › statements**, one folder per bank (TNG, Ryt
Bank, Maybank, Credit Card, AEON Bank, GX Bank). The setting is shared by
all your devices.

### One-time Google setup (for whoever runs the site)

1. In <https://console.cloud.google.com/>, create a project. No billing is
   needed.
2. **APIs & Services › Library**: enable **Google Sheets API** and **Google
   Drive API**.
3. **Google Auth Platform / OAuth consent screen**: External. Add your
   Google account under **Audience › Test users**. Scopes: `drive.file`
   (only files the app made, its spreadsheets included) and `drive.appdata`.
   The app never asks for access to all your spreadsheets.
4. **Credentials › Create credentials › OAuth client ID › Web
   application**. Authorised JavaScript origins:
   `https://chentzer.github.io` and `http://localhost:5173`.
5. On GitHub: repo **Settings › Secrets and variables › Actions ›
   Variables**. Add `GOOGLE_CLIENT_ID` (the Web client ID). Optionally add
   `ALLOWED_EMAILS` (comma-separated) to lock the site to those accounts.
   Until `GOOGLE_CLIENT_ID` is set, the site runs in demo mode with
   made-up data.

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

To run the Python tests:

```
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

## Supported sources

| Source | File | How it's recognised |
|---|---|---|
| AEON Bank (Savings Account-i + Savings pot) | PDF | `*Deposits-statement-*.pdf` |
| AEON Credit card | PDF, password in Settings › Passwords | `*e-statement*.pdf` that says AEON CREDIT SERVICE inside |
| GX Bank savings | PDF | `*-statement.pdf` that says GX Bank Berhad inside |
| Maybank savings (Maybank2u) | PDF | `M2U*.pdf` that says Malayan Banking Berhad inside |
| Ryt Bank (Main Account + pockets) | PDF | `Ryt_Bank*.pdf` |
| Touch 'n Go eWallet (wallet + GO+) | PDF (the current layout), password in Settings › Passwords | `*transactions*.pdf`, `tng*.pdf` |
| Maybank credit card | PDF | `<16-digit card no>_<YYYYMMDD>.pdf` |
| Splitwise group (Export as spreadsheet) | CSV | its header (Date, Description, Category, Cost, Currency, then members) |
| Accounts you kept yourself (e.g. "2022 Accounts.xlsx", template layout) | XLSX, in the app | month tabs with Date / Item / ... headers; rows copied as they are |


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

Maybank savings notes: payments to anyone in Settings › Own payees (by default
AEON CREDIT SERVICE, i.e. paying your card bill) are your own money moving,
and they pair with the CR on the card statement. Add other card issuers or
investment accounts you pay into there.

AEON Credit notes: every **CR** row is ignored: payments to the card,
points redemption and cashback. Items are the merchant name with the city
and country removed ("AEON BIG-JAYA ONE PETALING JAYAMY" → "AEON BIG-JAYA
ONE"), dated by transaction date. The parsed charges are checked against the
statement's "Total charges" and "Closing balance".

Splitwise notes: your column is found by your name (your Google account
name). What you paid is
spending: expenses where your balance went up, and solo expenses where every
balance is 0. Money paid back to you ("Bob paid Jane") is earnings; money you
paid a friend is spending. Expenses someone else paid, and payments between
other members, are left out. Amounts are converted to RM at the rate of the
trip in that currency (set in Trips), so spending during the trip lands
on the trip tab and repayments on the month tab. Remarks keep the original
amount ("Lunch · JPY 4,000.00"), and Splitwise categories like Dining out
fill Category. A later export of the same group only adds what's new.

A Splitwise row that is also on a statement (a dinner you paid by card, a
repayment that came in by DuitNow) is recorded once. Same direction, within
4 days, and the same RM amount; for another currency, one card charge within
3% of the converted amount. The row uploaded first stays and the other is
added to Settings › Removed; uploaded together, the bank row stays and takes
the Splitwise description and category. A closer call (up to 8% off, or two
charges that close), or a pair already in your sheet, gets a To Update card
on the Splitwise row: **Same** removes it, **Different** keeps both.

AEON Bank notes: moves between your account and your Savings pot are
internal. So are DuitNow transfers to or from your own name, which the
parser reads from the statement. Those are your money moving to another bank
or wallet, and they're paired with the other side when that statement is
imported. Each row is checked against the running balance, so if AEON
changes the PDF layout the run stops instead of giving wrong totals.

## What gets recorded

1. **Money between your own accounts is ignored**: savings pot moves, and
   transfers to or from your own name at another bank or wallet. When only
   one statement can tell (a card charge that reloaded your wallet), it's
   paired with the same amount on the other side within 3 days. At least one
   side must be known to be your own money, so an RM50 dinner and RM50 from a
   friend are both kept.
2. **Only your spending, and money in from other people, is recorded.**
3. **Everything else is recorded, and you fill in what the statement
   doesn't say.** If the statement gives a purpose, it becomes the Item:
   `JANE TAN - DuitNowID - lunch` becomes Item *Lunch*. If it doesn't (only
   "DuitNow QR" or a reference number), the row still goes in, as Item
   *Transfer* or *QR payment*, for you to fill in. Card charges use the shop
   name. Source is the bank or wallet; Remarks starts as the statement's own
   text and is yours to change.
   Category and Importance come from Settings › Rules, or are
   left blank and add up under **Not set** in the month's summary.

## Updating what the statement didn't say

Rows that still need what they were for, and/or a Category, get a **To
Update** card, shown one at a time right after an upload: Save, Skip, Not
mine, or move it to a trip. Cards you leave stay on the To Update tab, the
first tab of the spreadsheet. You can also fix a row straight in the month
tab, and its card closes on the next upload.

Names on the cards are shortened ("TAN MEI LING" → "Mei Ling"). To set a name
yourself, add it in Settings › People.

## Monthly accounts (your template)

Each upload writes to a Google Sheet named `<year> Accounts`, in the layout
of `Account Template.xlsx`:

- One tab per month (`July 2026`): **Spendings** in A–G (Date, Item,
  Category, Amount, Importance, Source, Remarks), **Earnings** in P–T (Date,
  Item, Amount, Source, Remarks), with a blank column between sections and
  coloured headers.
- Spending by Category (J–K), by Importance (M–N), and Earnings / Spendings /
  **Final** in W–X. Final carries over from the previous month.
- A **Year End Summary** tab with total earnings, spending and the difference.
- Category and Importance have the template's dropdowns. Settings › Rules
  fills what it can, and the rest is left blank for you.
- Source is the bank or wallet the row came from; Remarks starts as the
  statement text, for your own note.
- Internal transfers (wallet reloads, card repayments, GO+ moves) are left out.

Differences from the old workbook: the summaries are SUMIF formulas, not
pivot tables. Pivot tables don't survive the move to Google Sheets and need
manual refreshing. Final always sits in X6, and the Year End Summary adds up
every month tab (the 2022 formula skipped some months).

### Trips

Add a trip on the **Trips** screen (Accounts › Trips): name, dates,
currencies. It gets its own tab, laid out like the 2023 "Japan Trip" sheet:

| Columns | What | Filled by |
|---|---|---|
| A–G | RM spending: flights, hotels, card charges abroad | fincomp, from statements; or added in the app |
| J–M | Paid back to you (RM): friends' share of what you paid | you, or "Add transaction" (money in, on the trip) |
| P–Q | **Trip Total (RM)** in Q4 = spent in RM + each currency × its rate − paid back; then each currency's spending, rate and RM | formulas; rates from the trip's Edit screen |
| S– | One spending block per currency (a trip can have several, e.g. CHF, EUR, GBP), then money received in other currencies | you, or "Add transaction" paid in that currency |

What goes to the trip tab: statement spending dated within the trip, plus
earlier bookings whose description matches the trip's "Earlier bookings"
words, or any rule that sends to that trip. Money coming in stays on the
month tab.

Name the RM row for buying currency **Money Exchange** (rename it in the
sheet; your edit is kept). It's left out of "Spent in RM" because that
money is counted when you spend the yen.

The trip tab goes right after the month the trip starts. The month it ends
shows the trip total under **Trips** (X5), and that month's Final subtracts
it. The Year End Summary counts trips in Total Spending.

A trip's tab is made as soon as you add it ("Today's rate" fills in the
exchange rate). Open a trip and use **Edit trip** to change it: a new name
renames its tab, rows included. Deleting a trip sends its RM spending and
money paid back to the months they happened in; rows in another currency stay
on its tab, not counted. Any spending row can be moved onto a trip, or back,
from its edit screen, and "Add transaction" adds one by hand to a month or a
trip.

Tabs you make yourself, like "Chinese New Year", are never touched or moved.

### Sheets (your own tabs)

The app's **Sheets** section makes tabs of your own in a year's spreadsheet,
like an ang pao sheet: one or more tables side by side, each with a name, a
currency (RM, SGD, ...) and a name column ("Person"), with its total on top.
A sheet can count as earnings or spending, and then its RM tables are added
to the Year End Summary. Importing an old accounts workbook turns tabs like
2023's "Chinese New Year" into a sheet, counted the way the old Year End
Summary counted it.

**Uploading again is safe.** Columns H and U are hidden and hold a key for
each uploaded row. An upload only appends transactions that aren't in the
sheet yet, then sorts by date. Rows already there aren't rewritten, so Categories
you picked, items you renamed, and rows you typed in yourself (like cash
spending) are all kept.

While the Google app is in *Testing* mode, Google expires the sign-in after 7
days. To avoid this, set the consent screen's publishing status to *In
production*. For a personal app you don't need to go through verification.

## Adding a bank

Add a parser in `src/fincomp/parsers/` and register it in
`parsers/__init__.py`.

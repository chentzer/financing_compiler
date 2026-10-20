# FinMerge web + Android app

The phone/desktop front end for fincomp: React + TypeScript + Vite, wrapped
by Capacitor for Android. No server: the finished app runs the Python
`fincomp` package in Pyodide on the device and talks to Google Sheets /
Drive with the user's own sign-in.

**Status:** the web app works end to end with `VITE_BACKEND=real`
(`PyodideBackend`). `MockBackend` (made-up data, in memory) is the default
for development and is what the site shows until a Google client ID is
configured. The Android app signs in natively (`NativeAuth`) and is built
by GitHub Actions (see "Android" below). The website can also be installed
from Chrome on a phone (Add to Home screen): it has a web app manifest.

## Run

```
cd web
npm install
npm run dev        # http://localhost:5173, demo sign-in, synthetic data
npm run build      # type-check + production build into web/dist
```

Settings come from `.env.local` (see `.env.example`):
`VITE_BACKEND=mock|real` and `VITE_GOOGLE_CLIENT_ID`.

Demo upload: the file name picks the bank (`tng-oct.pdf`, `maybank.pdf`,
`aeon-credit.pdf`, `gx.pdf`, `ryt.pdf`); other names fail. TNG, AEON Credit
and Maybank card files ask for a password; any password except `wrong`
opens them.

## Screens

| Route | Screen |
|---|---|
| `#/` | Home: this month's Final / Spending / Earnings, "N to update", Upload |
| `#/upload` | Pick PDFs, per-file result (ok / failed / needs password), password prompt |
| `#/cards` | To Update, one card at a time: Save · Later · Not mine, "Same for every …" |
| `#/month/YYYY-MM` | Summary (Category, Importance, Earnings, Spendings, Trips, Final) + rows; tap to edit |
| `#/settings/<tab>` | Rules, People, Trips, Own payees, Passwords; account + sign out |

Hash routes so the same build works on GitHub Pages and in Capacitor.
Phone: bottom tab bar; 900px and wider: sidebar.

## Code

```
src/data/Backend.ts      the interface + types every screen uses (start here)
src/data/MockBackend.ts  in-memory implementation
src/data/mockData.ts     synthetic rows/cards/settings (made-up names only)
src/auth/Auth.ts         sign-in interface, scopes, allowed email
src/auth/GoogleWebAuth.ts  Google Identity Services token client (web)
src/auth/NativeAuth.ts   Android sign-in (@capgo/capacitor-social-login)
src/auth/DemoAuth.ts     fake sign-in for the mock
src/setup.ts             picks Auth + Backend from VITE_BACKEND
src/app/                 data context (useLoad, changed(), toast), hash router, formatting
src/screens/             Home, Upload, Cards, Month, Settings
src/components/CategoryPicker.tsx  category chips: suggestions first, "+ New" adds to your list
```

## The Backend interface

All data access goes through `Backend` (`src/data/Backend.ts`). Screens
never call Google or Pyodide directly. After a mutation a screen calls
`changed()`, and every `useLoad` refetches.

| Method | Real implementation should |
|---|---|
| `listMonths()` | list month tabs in "YYYY Accounts" sheets |
| `monthSummary(y, m)` / `monthRows(y, m)` | read the month tab (and trip tabs ending that month), compute via `sheetplan.month_summary` |
| `editRow(key, fields)` | `sheetplan.set_cells(key, fields)` → `values:batchUpdate`; closes the row's card if now complete |
| `listCards()` | read the sheet, `sheetplan.open_cards(values)` |
| `saveCard(key, answer)` | `set_cells`; `sameForEvery` adds a row to Settings › Rules (match = counterparty or statement) |
| `skipCard(key)` | nothing to write; the card stays in To Update |
| `notMine(key)` | `sheetplan.remove_row(key)` |
| `uploadStatements(files, passwords)` | Pyodide `pipeline` on the bytes, saved passwords from Drive App Data merged with typed ones, save a typed one once it opens a PDF; return one `UploadResult` per file (`status: 'password'` + `passwordFor` + `wrongPassword` when it can't open) |
| `getSettings()` / `saveSettings()` | the "fincomp Settings" sheet (Rules / People / Trips / Own payees tabs) |
| `getPasswords()` / `savePasswords()` | `passwords.json` in the Drive App Data folder |

Conventions: dates are ISO `YYYY-MM-DD`; `Row.amount` is always positive
with `kind` = `spend` | `earn` (as in the template); `key` is the hidden row
key from column G / R.

## The real backend

- `src/data/py/worker.ts` loads Pyodide 0.26 from the jsDelivr CDN in a Web
  Worker, installs `pypdf` (the version the Python tests use), and writes
  in the `fincomp` package from `public/py/fincomp.json`.
  `scripts/bundle-python.mjs` makes that file from `../src/fincomp` before
  every `dev`/`build`, leaving out the CLI-only modules.
- `src/data/py/client.ts`: `py(fn, args, files?)` calls a function in
  `fincomp/webapi.py` and gets JSON back.
- `src/data/google.ts`: the Sheets / Drive / App Data REST calls.
- `src/data/PyodideBackend.ts` implements `Backend`. Python decides what
  to write (`sheetplan.py`); this file only moves data.

In dev builds, `window.__fincompPy(fn, args)` calls the worker from the
browser console.

## What's left

- Upload progress: results come back when everything is done. Fine for a
  month of statements (about 6 s); add a per-file callback if it gets slow.

## Android (Capacitor)

The Android project is in `android/` (app id `com.chentzer.fincomp`). It's
the same web app; only sign-in differs: Google blocks its web sign-in inside
app WebViews, so `NativeAuth` uses Android's account picker
(`@capgo/capacitor-social-login`; `MainActivity.java` passes the
Sheets/Drive permission result back to it).

**Builds:** `.github/workflows/android.yml` builds a signed release APK on
every push to `main` and puts it on the `android` release:
https://github.com/chentzer/financing_compiler/releases/download/android/fincomp.apk
Open that on the phone to install or update (allow "install unknown apps"
for the browser the first time).

**One-time setup:**

1. Release key: `.signing/fincomp-release.jks` (gitignored; password in
   `.signing/password.txt`). Back both up: updates must be signed with the
   same key. Repo secrets `ANDROID_KEYSTORE_BASE64` (the .jks, base64) and
   `ANDROID_KEYSTORE_PASSWORD`.
2. Google Cloud console > APIs & Services > Credentials > Create
   credentials > OAuth client ID > **Android**: package
   `com.chentzer.fincomp`, SHA-1 of the release key
   (`keytool -list -v -keystore .signing/fincomp-release.jks -alias fincomp`).
   Same project as the website's Web client; nothing to copy back, the app
   uses the Web client ID (repo variable `GOOGLE_CLIENT_ID`).

Local builds (optional) need the Android SDK (Android Studio):

```
npm run cap:sync   # vite build + copy web/dist into the Android project
npm run cap:open   # open it in Android Studio
```

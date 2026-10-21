/**
 * Everything the screens know about data goes through this interface.
 *
 * Today the app runs on MockBackend (synthetic data, in memory). The real
 * implementation runs the Python `fincomp` package in Pyodide and talks to
 * the Sheets / Drive APIs with the user's Google token; it plugs in by
 * implementing this interface (see web/README.md).
 *
 * Conventions follow the Python core:
 * - Dates are ISO strings (YYYY-MM-DD).
 * - `amount` on a Row/Card is always positive, as in the accounts template;
 *   `kind` says whether it is spending ("spend") or money in ("earn").
 * - `key` is the hidden row key fincomp writes in column G / R.
 */

/** The starting list; yours lives in Settings › Lists and can grow (see listCategories). */
export const CATEGORIES = [
  'Bills',
  'Shopping',
  'Food',
  'Health',
  'Entertainment',
  'Transport',
  'Self-Development',
  'Misc',
] as const
/** Any name in your category list. */
export type Category = string

export const IMPORTANCE = ['Essential', 'Have to Have', 'Nice to Have', 'Courtesy', 'Regretted'] as const
export type Importance = (typeof IMPORTANCE)[number]

/** Parser keys that can have a PDF password, with the name shown in the UI. */
export const STATEMENT_SOURCES: { key: string; label: string }[] = [
  { key: 'tng', label: "Touch 'n Go eWallet" },
  { key: 'maybank_sa', label: 'Maybank savings' },
  { key: 'maybank_cc', label: 'Maybank credit card' },
  { key: 'aeon', label: 'AEON Bank' },
  { key: 'aeon_credit', label: 'AEON Credit' },
  { key: 'gx', label: 'GX Bank' },
  { key: 'ryt', label: 'Ryt Bank' },
]

export type Kind = 'spend' | 'earn'
/** What a card still needs: "purpose" (Item is only "Transfer"/"QR payment") and/or "category". */
export type Need = 'purpose' | 'category'

/** A recorded row as it sits in a month tab (or a trip tab). */
export interface Row {
  key: string
  kind: Kind
  date: string
  item: string
  amount: number
  /** Spending only; "" = not filled in. */
  category: Category | ''
  /** Spending only; "" = not filled in. */
  importance: Importance | ''
  /** Your note; starts as the statement's own text. */
  remarks: string
  /** Bank or wallet, e.g. "Maybank", "TNG"; or anything you type (e.g. "Cash"). */
  source: string
  /** Trip name when this spending lives on a trip tab. */
  trip?: string
}

/** A row from the "To Update" tab: a Row plus what the user still has to answer. */
export interface Card extends Row {
  needs: Need[]
  /** Raw statement description, shown on the card. */
  statement: string
  /** The person as on the statement; "" for a shop. Used for "Same for every…". */
  counterparty: string
}

export interface CardAnswer {
  item?: string
  category?: Category | ''
  importance?: Importance | ''
  /** Also add a rule so future rows from the same payee/shop get the same answer. */
  sameForEvery?: boolean
}

export type RowEdit = Partial<Pick<Row, 'item' | 'category' | 'importance' | 'remarks' | 'source'>>

/** A transaction typed in by hand. */
export interface NewRow {
  kind: Kind
  date: string
  item: string
  /** Positive; RM, or `currency` (one of the trip's). */
  amount: number
  category?: Category | ''
  importance?: Importance | ''
  source?: string
  remarks?: string
  /** Put it on this trip: spending goes in its RM or currency block, money in is "paid back to you". */
  trip?: string
  /** One of the trip's currencies; blank = RM. */
  currency?: string
}

export interface Month {
  year: number
  /** 1-12 */
  month: number
}

export interface MonthSummary extends Month {
  byCategory: { name: Category | ''; amount: number }[]
  byImportance: { name: Importance | ''; amount: number }[]
  earnings: number
  spendings: number
  /** Trips ending this month (their totals come off Final). */
  trips: { name: string; total: number }[]
  tripsTotal: number
  /** earnings - spendings - tripsTotal (T6 in the template). */
  final: number
}

export interface UploadFile {
  name: string
  data: Uint8Array
}

export type UploadStatus = 'ok' | 'failed' | 'password'

export interface UploadResult {
  file: string
  status: UploadStatus
  /** Parser that read it, e.g. "tng". */
  source?: string
  /** Shown under the file: what was added, or which check failed. */
  message: string
  rowsAdded?: number
  cardsAdded?: number
  /** status "password": which saved password is missing/wrong (a STATEMENT_SOURCES key). */
  passwordFor?: string
  /** status "password": true when a password was tried and didn't open the PDF. */
  wrongPassword?: boolean
}

export interface Rule {
  /** Case-insensitive piece of the statement description. */
  match: string
  /** Only for this bank/wallet (parser key); "" = any. */
  source?: string
  item?: string
  category?: Category | ''
  importance?: Importance | ''
  trip?: string
  /** Leave matching rows out. */
  skip?: boolean
}

export interface Person {
  /** Name as on the statement, e.g. "TAN MEI JANE". */
  statementName: string
  /** How it shows in Remarks, e.g. "Jane Tan". */
  shownAs: string
}

export interface TripCurrency {
  /** e.g. "JPY". */
  code: string
  /** RM per 1 unit. */
  rate?: number
}

export interface Trip {
  name: string
  start: string
  end: string
  /** Foreign currencies, each with its own spending block and RM rate; [] for a trip in RM only. */
  currencies: TripCurrency[]
  /** Statement pieces that send earlier bookings to this trip. */
  match: string[]
  link?: string
}

/** A trip with its total (Q4 of its tab: what you really paid, in RM). */
export interface TripTotal {
  trip: Trip
  /** The spreadsheet it's in (the year it starts). */
  year: number
  /** null: no tab yet. */
  total: number | null
}

/** A row on a trip tab. `currency` only on money received in other currencies. */
export interface TripRow {
  date: string
  item: string
  amount: number
  category?: string
  importance?: string
  source?: string
  remarks: string
  currency?: string
}

export interface TripDetail {
  name: string
  start: string
  end: string
  /** RM spent + each currency's spending x its rate - paid back. */
  total: number
  spentRm: number
  paidBack: number
  rm: TripRow[]
  /** Paid back to you (RM). */
  paid: TripRow[]
  currencies: { code: string; rate?: number | null; spent: number; rm: number; rows: TripRow[] }[]
  /** Money received in other currencies (money exchange, leftovers). */
  received: TripRow[]
}

/** A year's totals, from its month tabs and Year End Summary. */
export interface YearSummary {
  year: number
  months: { month: number; earnings: number; spendings: number; trips: number; final: number }[]
  byCategory: { name: string; amount: number }[]
  earnings: number
  /** Not counting trips. */
  spendings: number
  trips: number
  /** earnings - spendings - trips */
  final: number
}

/** How far an upload has got: 0..1, and what it's doing now. */
export interface UploadProgress {
  fraction: number
  step: string
}

/** One table on a custom sheet: Date | <label> | Amount (<currency>) | Remarks. */
export interface SheetTable {
  name: string
  currency: string
  /** The second column, e.g. "Person" for ang pao. */
  label: string
}

/** A tab of your own in a year's spreadsheet (Sheets section), e.g. "Chinese New Year". */
export interface CustomSheet {
  name: string
  year: number
  /** RM tables count towards the Year End Summary as this; "" = not counted. */
  counts: '' | 'earnings' | 'spending'
  tables: SheetTable[]
  /** Groups sheets in the app; "Investments" ones are on their own tab. */
  category?: string
}

/** Sheets in this category are on the Investments tab instead of Sheets. */
export const INVESTMENTS = 'Investments'
/** Words that mean the same group, whatever a year's sheet was called. */
const GROUPS: [RegExp, string][] = [
  [/invest|stock|share|unit trust|crypto|\basb\b|\bepf\b|dividend/i, INVESTMENTS],
  [/\bcny\b|chinese new year|new years?\b|ang ?pa[ow]|hong ?bao|red packet|lunar new year/i, 'Chinese New Year'],
]

/** Which group a sheet sits in: its category (or name), tidied so every year's sheet for the
 * same thing lands together ("CNY", "New Years", "Chinese New Year 2026" → Chinese New Year). */
export function sheetCategory(s: Pick<CustomSheet, 'name' | 'category'>): string {
  const text = (s.category ?? '').trim() || s.name
  for (const [re, group] of GROUPS) if (re.test(text)) return group
  return text.replace(/\s*\(?\b(19|20)\d{2}\)?\s*$/, '').trim() || text
}
export const isInvestment = (s: Pick<CustomSheet, 'name' | 'category'>) => sheetCategory(s).toLowerCase() === INVESTMENTS.toLowerCase()

export interface SheetRow {
  key: string
  date: string
  item: string
  amount: number
  remarks: string
}

export interface SheetTableRows extends SheetTable {
  index: number
  total: number
  rows: SheetRow[]
}

/** Lives in the "fincomp Settings" sheet. */
export interface Settings {
  rules: Rule[]
  people: Person[]
  trips: Trip[]
  /** Payees that are the user's own money moving (card bills, investments). */
  ownPayees: string[]
}

/** PDF passwords keyed by STATEMENT_SOURCES key. Encrypted with the user's PIN (see vault.ts). */
export type Passwords = Record<string, string>

/**
 * The saved passwords' lock:
 * - "new": no PIN yet (nothing saved, or only an old unencrypted file to convert)
 * - "locked": saved and encrypted; the PIN is needed on this device
 * - "unlocked": usable now (PIN entered, or remembered on this device)
 */
export type VaultState = 'new' | 'locked' | 'unlocked'

export interface Backend {
  /** Months that have a tab, oldest first. */
  listMonths(): Promise<Month[]>
  monthSummary(year: number, month: number): Promise<MonthSummary>
  monthRows(year: number, month: number): Promise<Row[]>
  editRow(key: string, fields: RowEdit): Promise<void>

  /** Add a transaction yourself; it can be edited and moved like any other. */
  addRow(row: NewRow): Promise<void>
  /** Move a spending row to a trip, or back to its month (`trip` null). */
  moveRow(key: string, trip: string | null): Promise<void>

  /** Open To Update cards, oldest first. */
  listCards(): Promise<Card[]>
  saveCard(key: string, answer: CardAnswer): Promise<void>
  /** "Skip": keep the row as recorded and never ask about it again. */
  keepAsIs(key: string): Promise<void>
  /** "Later": leave it in To Update. */
  skipCard(key: string): Promise<void>
  /** "Not mine": remove the row from its block. */
  notMine(key: string): Promise<void>

  /**
   * Parse, record and sync statements. `passwords` are extra ones typed in
   * this upload (keyed by source); saved passwords are used automatically,
   * and a typed one is saved after it opens a PDF.
   */
  uploadStatements(files: UploadFile[], passwords?: Passwords, onProgress?: (p: UploadProgress) => void): Promise<UploadResult[]>
  /** Keep a copy of each uploaded PDF in Drive › fincomp › statements (off: read, then discarded). */
  getKeepPdfCopies(): Promise<boolean>
  setKeepPdfCopies(on: boolean): Promise<void>

  /** Years that have a spreadsheet, oldest first. */
  listYears(): Promise<number[]>
  yearSummary(year: number): Promise<YearSummary>
  /** Every trip in Settings › Trips with its total. */
  listTrips(): Promise<TripTotal[]>
  tripDetail(name: string): Promise<TripDetail>

  /** Your own sheets (Sheets section). */
  listSheets(): Promise<CustomSheet[]>
  /** Make or change a sheet (its tab follows). Tables can be added or renamed, never removed. */
  saveSheet(sheet: CustomSheet, previousName?: string): Promise<void>
  sheetRows(name: string): Promise<SheetTableRows[]>
  addSheetRow(name: string, table: number, row: Omit<SheetRow, 'key'>): Promise<void>
  editSheetRow(name: string, key: string, fields: Partial<Omit<SheetRow, 'key'>>): Promise<void>
  deleteSheetRow(name: string, key: string): Promise<void>
  /** Take a sheet out of the app; `deleteTab` also deletes its tab (and rows) in Google Sheets. */
  deleteSheet(name: string, deleteTab: boolean): Promise<void>
  /** Link to the sheet's tab in Google Sheets, to edit it there; null when it has no tab. */
  sheetLink(name: string): Promise<string | null>

  /** Your category list (Settings › Lists). */
  listCategories(): Promise<Category[]>
  /** Replace the list (add, rename, remove, reorder). Month tabs' "By Category" and dropdowns follow. */
  saveCategories(names: Category[]): Promise<void>
  /** Up to 3 categories to offer first on a card, from your past rows and common shop words. */
  suggestCategories(cardKey: string, item: string): Promise<Category[]>

  getSettings(): Promise<Settings>
  saveSettings(settings: Settings): Promise<void>

  vaultState(): Promise<VaultState>
  /** Throws WrongPinError (vault.ts) for a wrong PIN. */
  unlockVault(pin: string, rememberHere: boolean): Promise<void>
  /** Set a PIN the first time, or change it (needs the vault unlocked). New random salt each time. */
  setVaultPin(pin: string, rememberHere: boolean): Promise<void>
  /** Forget the PIN on this device. */
  lockVault(): Promise<void>
  /** Need the vault unlocked. */
  getPasswords(): Promise<Passwords>
  savePasswords(passwords: Passwords): Promise<void>
}

/**
 * The real Backend: no server. Statements are parsed on this device by the
 * fincomp Python package (Pyodide worker, see py/), and everything is read
 * from and written to the user's own Google Drive:
 *
 *   "fincomp Settings"  Rules / People / Trips / Own payees / Lists /
 *                       Removed / Ledger (hidden: every parsed transaction)
 *   "<year> Accounts"   month tabs, trip tabs, To Update, Year End Summary
 *   App Data folder     passwords.vault.json (statement passwords, encrypted with your PIN),
 *                       prefs.json (e.g. whether to keep PDF copies)
 *   fincomp/statements  copies of the uploaded PDFs in a folder per bank, only if you turned that on
 *
 * What to write is decided in Python (sheetplan.py via webapi.py); this
 * file only moves data between Pyodide and the Google APIs.
 */
import type { Auth } from '../auth/Auth'
import {
  IMPORTANCE,
  type Backend,
  type Card,
  type CardAnswer,
  type CustomSheet,
  type SheetRow,
  type SheetTableRows,
  type Category,
  type Importance,
  type Month,
  type MonthSummary,
  type NewRow,
  type Passwords,
  type Row,
  type RowEdit,
  type Rule,
  type Settings,
  type TripDetail,
  type TripTotal,
  type UploadFile,
  type UploadProgress,
  type UploadResult,
  type YearSummary,
  type VaultState,
} from './Backend'
import { Google, type SheetTab, type Values } from './google'
import { py, warmUp } from './py/client'
import * as vault from './vault'
import { keepLocal, localBlob, type VaultBlob } from './vault'

const SETTINGS_TITLE = 'fincomp Settings'
// Encrypted passwords (vault.ts); the old readable file is converted once, then deleted.
const VAULT_FILE = 'passwords.vault.json'
const LEGACY_PASSWORDS_FILE = 'passwords.json'
const PREFS_FILE = 'prefs.json'
/** Subfolder of Drive › fincomp › statements for each parser's PDFs. */
const COPY_FOLDERS: Record<string, string> = {
  tng: 'TNG', ryt: 'Ryt Bank', maybank_sa: 'Maybank', maybank_cc: 'Credit Card', aeon_credit: 'Credit Card',
  aeon: 'AEON Bank', gx: 'GX Bank',
}
const TO_UPDATE = 'To Update'
const SHEET_MIME = 'application/vnd.google-apps.spreadsheet'
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December']
const SETTINGS_RANGES: Record<string, string> = {
  Rules: "'Rules'!A1:H", People: "'People'!A1:B", Trips: "'Trips'!A1:H", 'Own payees': "'Own payees'!A1:A",
  Lists: "'Lists'!A1:B", Removed: "'Removed'!A1:D", Reviewed: "'Reviewed'!A1:D", Sheets: "'Sheets'!A1:D",
}
const LEDGER_RANGE = "'Ledger'!A1:N"
const LATER_KEY = 'fincomp.later'

interface FileOut { name: string; source: string; parser: string; count: number; error: string; needs_password: string; ok: boolean }
interface CompileOut { files: FileOut[]; ledger: Values; years: number[]; pairs: number; duplicates: number; toUpdate: number }
interface Prep { add: { title: string; index: number; rows: number; cols: number }[]; delete: string[]; reads: string[]; widths?: Record<string, number> }
interface Fin { clear: string[]; data: { range: string; values: unknown[][] }[]; requests: object[]; added: number; already: number; toUpdate: number }
interface PyCard { row: number; date: string | null; amount: number; who: string; statement: string; recordedAs: string; needsPurpose: boolean; needsCategory: boolean; tab: string; key: string }
interface PyRow { kind: 'spend' | 'earn'; row: number; date: string | null; item: string; category: string; amount: number; importance: string; source: string; remarks: string; key: string }
interface Target { title: string; trip: boolean; year: number; currencies: string[] }
type Plan = { clear: string[]; data: { range: string; values: unknown[][] }[]; requests: object[] }
interface Book { year: number; id: string }
type Tell = (fraction: number, step: string) => void
interface Where { book: Book; tab: string; trip: boolean }

const monthTitle = (y: number, m: number) => `${MONTHS[m - 1]} ${y}`
const quote = (t: string) => `'${t.replace(/'/g, "''")}'`
const isMonthTab = (t: string) => new RegExp(`^(${MONTHS.join('|')}) \\d{4}$`).test(t)
const s = (v: unknown) => (v === undefined || v === null ? '' : String(v).trim())
/** Key for a row you typed in (statement rows get theirs from their contents). */
const newKey = () => 'm-' + crypto.randomUUID().replace(/-/g, '').slice(0, 12)

export class PyodideBackend implements Backend {
  private g: Google
  private settingsId?: string
  private books?: Book[]
  private rowsAt = new Map<string, Where>()
  private cardsAt = new Map<string, Where & { card: Card }>()

  private auth: Auth

  /** Your names, to find your column in a Splitwise export. */
  private me(): string[] {
    const u = this.auth.currentUser()
    return u ? [u.name ?? '', u.email.split('@')[0].replace(/[._]+/g, ' ')] : []
  }

  constructor(auth: Auth) {
    this.auth = auth
    this.g = new Google(() => auth.getAccessToken())
    warmUp()
  }

  // ---- spreadsheets ---------------------------------------------------------------

  private async settingsBook(): Promise<string> {
    if (this.settingsId) return this.settingsId
    const found = await this.g.findFiles(SETTINGS_TITLE, SHEET_MIME)
    this.settingsId = found.length ? found[0].id : await this.createSettings()
    return this.settingsId
  }

  private async createSettings(): Promise<string> {
    const t = await py<{ title: string; tabs: Record<string, Values>; hidden: string[] }>('settings_template', [])
    const id = await this.g.createSpreadsheet(t.title)
    const first = (await this.g.tabs(id))[0]
    const names = Object.keys(t.tabs)
    await this.g.batch(id, [
      ...names.map((title, index) => ({
        addSheet: { properties: { title, index, hidden: t.hidden.includes(title), gridProperties: { rowCount: 500, columnCount: 14 } } },
      })),
      { deleteSheet: { sheetId: first.sheetId } },
    ])
    await this.g.write(id, names.map((n) => ({ range: `${quote(n)}!A1`, values: t.tabs[n] })), 'RAW')
    return id
  }

  private async yearBooks(): Promise<Book[]> {
    if (!this.books) {
      const files = await this.g.findSpreadsheets(' Accounts')
      this.books = files
        .map((f) => ({ id: f.id, m: /^(\d{4}) Accounts$/.exec(f.name) }))
        .filter((f) => f.m)
        .map((f) => ({ year: +f.m![1], id: f.id }))
        .sort((a, b) => a.year - b.year)
    }
    // Once per visit, before anything reads or writes rows.
    this.upgraded ??= this.upgradeLayout(this.books).catch((e) => {
      this.upgraded = undefined
      throw e
    })
    await this.upgraded
    return this.books
  }

  private upgraded?: Promise<void>

  /** Tabs made before the Source and gap columns get them (sheetplan.upgrade_finish): columns
   * are inserted, so rows, your edits and formulas pointing at them move along. */
  private async upgradeLayout(books: Book[]): Promise<void> {
    let compiled = false
    for (const b of books) {
      await this.useSettings()
      const { tabs, ids } = await this.ids(b.id)
      const titles = tabs.map((t) => t.title)
      const headers = await py<string[]>('upgrade_headers', [b.year, titles])
      if (!headers.length) continue
      const got = await this.g.read(b.id, headers, 'UNFORMATTED_VALUE')
      const plan = await py<{ requests: object[]; finish: string[]; trips: Record<string, string> }>(
        'upgrade_columns', [ids, Object.fromEntries(headers.map((r, i) => [r, got[i]]))])
      if (!plan.finish.length && !Object.keys(plan.trips).length) continue
      if (plan.requests.length) await this.g.batch(b.id, plan.requests)
      if (!compiled) {
        // Each row's bank and statement text, from the Ledger.
        const st = await this.readSettings()
        await py('recompile', [st.values, {}, st.ledger])
        compiled = true
      }
      const reads = await py<string[]>('book_ranges', [b.year, titles])
      const vals = await this.g.read(b.id, reads, 'FORMULA')
      if (plan.finish.length) {
        const fin = await py<Plan>('upgrade_finish', [ids, plan.finish, Object.fromEntries(reads.map((r, i) => [r, vals[i]]))])
        await this.run(b.id, fin)
      }
      if (Object.keys(plan.trips).length) {
        // Trip tabs in an older layout are rewritten in the current one (rows kept).
        const tripReads = await py<string[]>('upgrade_trip_ranges', [plan.trips])
        const tv = await this.g.read(b.id, tripReads, 'FORMULA')
        const fin = await py<Plan>('upgrade_trips', [b.year, titles, ids, plan.trips,
          Object.fromEntries(tripReads.map((r, i) => [r, tv[i]]))])
        // Requests first: they widen the tab the clear and the new blocks need.
        await this.run(b.id, { clear: [], data: [], requests: fin.requests })
        await this.run(b.id, { ...fin, requests: [] })
      }
    }
  }

  private async run(bookId: string, plan: Plan): Promise<void> {
    if (plan.clear.length) await this.g.clear(bookId, plan.clear)
    if (plan.data.length) await this.g.write(bookId, plan.data, 'USER_ENTERED')
    if (plan.requests.length) await this.g.batch(bookId, plan.requests)
  }

  private configured = false

  /** Give Python the Settings (rules, trips, lists; not the Ledger) once. */
  private async useSettings(force = false): Promise<void> {
    if (this.configured && !force) return
    const id = await this.settingsBook()
    const names = await this.settingsTabs(id)
    const got = await this.g.read(id, names.map((n) => SETTINGS_RANGES[n]), 'UNFORMATTED_VALUE')
    await py('use_settings', [Object.fromEntries(names.map((n, i) => [n, got[i]]))])
    this.configured = true
  }

  /** Every month and trip tab's rows in a book, to find a row by key wherever it is. */
  private async bookValues(book: Book): Promise<{ values: Record<string, Values>; ids: Record<string, number> }> {
    await this.useSettings()
    const { tabs, ids } = await this.ids(book.id)
    const ranges = await py<string[]>('book_ranges', [book.year, tabs.map((t) => t.title)])
    const vals = await this.g.read(book.id, ranges, 'FORMULA')
    return { values: Object.fromEntries(ranges.map((r, i) => [r, vals[i]])), ids }
  }

  private async book(year: number): Promise<Book | undefined> {
    return (await this.yearBooks()).find((b) => b.year === year)
  }

  private async ids(id: string): Promise<{ tabs: SheetTab[]; ids: Record<string, number> }> {
    const tabs = await this.g.tabs(id)
    return { tabs, ids: Object.fromEntries(tabs.map((t) => [t.title, t.sheetId])) }
  }

  private async readSettings(): Promise<{ id: string; values: Record<string, Values>; ledger: Values }> {
    const id = await this.settingsBook()
    const names = await this.settingsTabs(id)
    const got = await this.g.read(id, [...names.map((n) => SETTINGS_RANGES[n]), LEDGER_RANGE], 'UNFORMATTED_VALUE')
    const values = Object.fromEntries(names.map((n, i) => [n, got[i]]))
    return { id, values, ledger: got[names.length] }
  }

  // ---- months -------------------------------------------------------------------------

  async listMonths(): Promise<Month[]> {
    const months: Month[] = []
    for (const b of await this.yearBooks()) {
      for (const t of await this.g.tabs(b.id)) {
        if (!isMonthTab(t.title)) continue
        const [name, year] = t.title.split(' ')
        months.push({ year: +year, month: MONTHS.indexOf(name) + 1 })
      }
    }
    return months.sort((a, b) => a.year - b.year || a.month - b.month)
  }

  async monthSummary(year: number, month: number): Promise<MonthSummary> {
    const empty: MonthSummary = { year, month, byCategory: [], byImportance: [], earnings: 0, spendings: 0, trips: [], tripsTotal: 0, final: 0 }
    const b = await this.book(year)
    const title = monthTitle(year, month)
    if (!b || !(await this.g.tabs(b.id)).some((t) => t.title === title)) return empty
    const ranges = await py<string[]>('summary_ranges', [title])
    const [cats, imps, totals] = await this.g.read(b.id, ranges, 'UNFORMATTED_VALUE')
    const sm = await py<{ byCategory: Record<string, number>; byImportance: Record<string, number>; earnings: number; spendings: number; trips: number; final: number }>(
      'month_summary', [cats, imps, totals])
    // Which trips ended this month: the names in the Trips cell's formula.
    const cells = await this.cells()
    const [[t5 = '']] = (await this.g.read(b.id, [`${quote(title)}!${cells.trips}`], 'FORMULA')).map((v) => v[0] ?? [''])
    const names = [...String(t5).matchAll(new RegExp(`'((?:[^']|'')+)'!${cells.tripTotal}`, 'g'))].map((m) => m[1].replace(/''/g, "'"))
    const totalsByTrip = names.length ? await this.g.read(b.id, names.map((n) => `${quote(n)}!${cells.tripTotal}`), 'UNFORMATTED_VALUE') : []
    const trips = names.map((name, i) => ({ name, total: Number(totalsByTrip[i]?.[0]?.[0] ?? 0) }))
    const named = <T extends string>(rec: Record<string, number>, allowed: readonly T[]) =>
      Object.entries(rec)
        .filter(([k]) => k !== 'Total' && (k === 'Not set' || (allowed as readonly string[]).includes(k)))
        .map(([k, amount]) => ({ name: (k === 'Not set' ? '' : k) as T | '', amount }))
        .filter((c) => c.name !== '' || c.amount > 0)
    return {
      year, month,
      byCategory: named<Category>(sm.byCategory, await this.listCategories()),
      byImportance: named<Importance>(sm.byImportance, IMPORTANCE),
      earnings: sm.earnings, spendings: sm.spendings, trips, tripsTotal: sm.trips, final: sm.final,
    }
  }

  private layout?: { trips: string; tripTotal: string }

  private async cells(): Promise<{ trips: string; tripTotal: string }> {
    this.layout ??= await py<{ trips: string; tripTotal: string }>('layout_cells', [])
    return this.layout
  }

  async monthRows(year: number, month: number): Promise<Row[]> {
    const b = await this.book(year)
    const title = monthTitle(year, month)
    if (!b || !(await this.g.tabs(b.id)).some((t) => t.title === title)) return []
    const ranges = await py<string[]>('tab_ranges', [title, false])
    const [spend, earn] = await this.g.read(b.id, ranges, 'UNFORMATTED_VALUE')
    const rows = await py<PyRow[]>('month_rows', [spend, earn])
    return rows.map((r) => {
      const key = r.key || `manual:${title}:${r.kind}:${r.row}`
      if (r.key) this.rowsAt.set(key, { book: b, tab: title, trip: false })
      return {
        key, kind: r.kind, date: r.date ?? '', item: r.item, amount: r.amount,
        category: (r.category || '') as Category | '', importance: (r.importance || '') as Importance | '',
        remarks: r.remarks, source: r.source,
      }
    })
  }

  async editRow(key: string, fields: RowEdit): Promise<void> {
    if (key.startsWith('manual:')) throw new Error('This row was typed in by hand: edit it in Google Sheets.')
    const where = this.rowsAt.get(key) ?? this.cardsAt.get(key)
    if (!where) throw new Error('That row is no longer in the sheet. Reload and try again.')
    await this.writeFields(where, key, fields)
    const card = this.cardsAt.get(key)?.card
    if (card && closes({ ...card, ...fields } as Card)) await this.removeCard(where.book, key)
  }

  private async writeFields(where: Where, key: string, fields: RowEdit | Record<string, string>): Promise<void> {
    // The whole book: the row may have been moved to a trip.
    const { values, ids } = await this.bookValues(where.book)
    const plan = await py<{ data: { range: string; values: unknown[][] }[] }>('edit_row', [key, values, ids, fields])
    if (!plan.data.length) throw new Error('That row is no longer in the sheet. Reload and try again.')
    await this.g.write(where.book.id, plan.data, 'USER_ENTERED')
  }

  // ---- cards ----------------------------------------------------------------------------

  async listCards(): Promise<Card[]> {
    const later = readLater()
    const out: Card[] = []
    this.cardsAt.clear()
    for (const b of await this.yearBooks()) {
      if (!(await this.g.tabs(b.id)).some((t) => t.title === TO_UPDATE)) continue
      const [rows] = await this.g.read(b.id, [`${quote(TO_UPDATE)}!A2:H`], 'UNFORMATTED_VALUE')
      for (const c of await py<PyCard[]>('cards', [rows])) {
        const person = /^(To|From) /.test(c.who)
        const card: Card = {
          key: c.key, kind: c.amount < 0 ? 'spend' : 'earn', date: c.date ?? '', item: c.recordedAs,
          amount: Math.abs(c.amount), category: '', importance: '', remarks: c.who, source: '',
          needs: [...(c.needsPurpose ? ['purpose' as const] : []), ...(c.needsCategory ? ['category' as const] : [])],
          statement: c.statement,
          counterparty: person ? c.statement.split(' - ')[0].replace(/^(From|To) /, '') : '',
        }
        this.cardsAt.set(c.key, { book: b, tab: c.tab, trip: !isMonthTab(c.tab), card })
        out.push(card)
      }
    }
    const rank = (c: Card) => (later.includes(c.key) ? 1 : 0)
    return out.sort((a, b) => rank(a) - rank(b) || a.date.localeCompare(b.date))
  }

  async saveCard(key: string, answer: CardAnswer): Promise<void> {
    const at = this.cardsAt.get(key)
    if (!at) throw new Error('That card was already closed. Reload to see what is left.')
    const fields: Record<string, string> = {}
    if (answer.item) fields.item = answer.item
    if (answer.category) fields.category = answer.category
    if (answer.importance) fields.importance = answer.importance
    if (Object.keys(fields).length) await this.writeFields(at, key, fields)
    await this.removeCard(at.book, key)
    writeLater(readLater().filter((k) => k !== key))
    if (answer.category) this.history?.push([answer.item || at.card.item, at.card.remarks, answer.category])

    if (answer.sameForEvery) {
      const match = at.card.counterparty || at.card.statement
      const row = await py<unknown[]>('rule_row', [match, answer.item ?? '', answer.category ?? '', answer.importance ?? ''])
      await this.g.append(await this.settingsBook(), "'Rules'!A:H", [row])
      // The new rule also answers the other open cards from the same payee/shop.
      for (const [k, other] of [...this.cardsAt]) {
        if (k === key || (other.card.counterparty || other.card.statement) !== match || other.card.kind !== at.card.kind) continue
        if (Object.keys(fields).length) await this.writeFields(other, k, fields)
        await this.removeCard(other.book, k)
      }
    }
  }

  // ---- custom sheets (Sheets section) --------------------------------------------------

  // ---- years and trips (Home, Trips) -----------------------------------------------------

  async listYears(): Promise<number[]> {
    return (await this.yearBooks()).map((b) => b.year)
  }

  async yearSummary(year: number): Promise<YearSummary> {
    const b = await this.book(year)
    const empty: YearSummary = { year, months: [], byCategory: [], earnings: 0, spendings: 0, trips: 0, final: 0 }
    if (!b) return empty
    const titles = (await this.g.tabs(b.id)).map((t) => t.title)
    const ranges = await py<string[]>('year_ranges', [year, titles])
    if (!ranges.length) return empty
    const values = await this.g.read(b.id, ranges, 'UNFORMATTED_VALUE')
    const y = await py<Omit<YearSummary, 'byCategory'> & { byCategory: Record<string, number> }>('year_totals', [year, titles, values])
    const byCategory = Object.entries(y.byCategory)
      .map(([name, amount]) => ({ name: name === 'Not set' ? '' : name, amount }))
      .filter((c) => c.amount > 0)
      .sort((a, b) => b.amount - a.amount)
    return { ...y, byCategory }
  }

  async listTrips(): Promise<TripTotal[]> {
    const trips = (await this.getSettings()).trips
    const cells = await this.cells()
    const out: TripTotal[] = trips.map((trip) => ({ trip, year: +trip.start.slice(0, 4), total: null }))
    for (const b of await this.yearBooks()) {
      const mine = out.filter((t) => t.year === b.year)
      if (!mine.length) continue
      const titles = new Set((await this.g.tabs(b.id)).map((t) => t.title))
      const here = mine.filter((t) => titles.has(t.trip.name))
      const got = await this.g.read(b.id, here.map((t) => `${quote(t.trip.name)}!${cells.tripTotal}`), 'UNFORMATTED_VALUE')
      here.forEach((t, i) => (t.total = Number(got[i]?.[0]?.[0] ?? 0)))
    }
    return out.sort((a, b) => b.trip.start.localeCompare(a.trip.start))
  }

  async tripDetail(name: string): Promise<TripDetail> {
    await this.useSettings()
    const trip = (await this.getSettings()).trips.find((t) => t.name === name)
    if (!trip) throw new Error(`No trip called "${name}" in Settings › Trips.`)
    const b = await this.book(+trip.start.slice(0, 4))
    const has = b && (await this.g.tabs(b.id)).some((t) => t.title === name)
    const [values] = has ? await this.g.read(b!.id, [await py<string>('trip_range', [name])], 'UNFORMATTED_VALUE') : [[]]
    return py<TripDetail>('trip_detail', [name, values])
  }

  async listSheets(): Promise<CustomSheet[]> {
    await this.useSettings()
    return py<CustomSheet[]>('sheets_list', [])
  }

  async saveSheet(sheet: CustomSheet, previousName?: string): Promise<void> {
    const list = await this.listSheets()
    const i = list.findIndex((s) => s.name === (previousName ?? sheet.name))
    if (i >= 0 && list[i].year !== sheet.year) throw new Error("A sheet's year can't change.")
    const next = i >= 0 ? list.map((s, j) => (j === i ? sheet : s)) : [...list, sheet]
    // Settings › Sheets (a Settings sheet made before sheets existed gets the tab now).
    const id = await this.settingsBook()
    await this.ensureSettingsTab(id, 'Sheets', ['Name', 'Year', 'Counts as (earnings / spending / blank)', 'Tables (name / currency / column ; ...)'])
    const rows = await py<unknown[][]>('sheets_rows', [next])
    await this.g.clear(id, ["'Sheets'!A2:D"])
    if (rows.length) await this.g.write(id, [{ range: "'Sheets'!A2", values: rows }], 'RAW')
    await this.useSettings(true)

    // Its tab in that year's spreadsheet.
    let book = await this.book(sheet.year)
    let created = false
    if (!book) {
      book = { year: sheet.year, id: await this.g.createSpreadsheet(await py<string>('spreadsheet_title', [sheet.year])) }
      this.books = [...(this.books ?? []), book].sort((a, b) => a.year - b.year)
      created = true
    }
    let tabs = await this.g.tabs(book.id)
    const old = previousName && previousName !== sheet.name ? tabs.find((t) => t.title === previousName) : undefined
    if (old) {
      await this.g.batch(book.id, [{ updateSheetProperties: { properties: { sheetId: old.sheetId, title: sheet.name }, fields: 'title' } }])
    } else if (!tabs.some((t) => t.title === sheet.name)) {
      const before = tabs.findIndex((t) => t.title === 'Year End Summary')
      await this.g.batch(book.id, [
        { addSheet: { properties: { title: sheet.name, index: before >= 0 ? before : tabs.length, gridProperties: { rowCount: 1000, columnCount: Math.max(12, sheet.tables.length * 6 + 2) } } } },
        ...(created ? [{ deleteSheet: { sheetId: tabs[0].sheetId } }] : []),
      ])
    }
    tabs = await this.g.tabs(book.id)
    const tab = tabs.find((t) => t.title === sheet.name)!
    const cols = sheet.tables.length * 6 + 2
    await this.g.batch(book.id, [{ updateSheetProperties: { properties: { sheetId: tab.sheetId, gridProperties: { columnCount: Math.max(cols, 12) } }, fields: 'gridProperties.columnCount' } }])
    const setup = await py<{ data: Plan['data']; requests: object[] }>('custom_setup', [sheet.name, tab.sheetId])
    await this.run(book.id, { clear: [], ...setup })
    if (tabs.some((t) => t.title === 'Year End Summary')) {
      await this.g.write(book.id, await py<Plan['data']>('year_summary', [sheet.year, tabs.map((t) => t.title)]), 'USER_ENTERED')
    }
  }

  private async sheetBook(name: string): Promise<{ book: Book; ranges: string[]; sheetId: number } | null> {
    const sheet = (await this.listSheets()).find((s) => s.name === name)
    if (!sheet) throw new Error(`No sheet called "${name}".`)
    const book = await this.book(sheet.year)
    const tab = book ? (await this.g.tabs(book.id)).find((t) => t.title === name) : undefined
    if (!book || !tab) return null
    return { book, ranges: await py<string[]>('custom_ranges', [name]), sheetId: tab.sheetId }
  }

  async sheetRows(name: string): Promise<SheetTableRows[]> {
    const at = await this.sheetBook(name)
    const values: Record<string, Values> = {}
    if (at) {
      const vals = await this.g.read(at.book.id, at.ranges, 'UNFORMATTED_VALUE')
      at.ranges.forEach((r, i) => (values[r] = vals[i]))
    }
    return py<SheetTableRows[]>('custom_rows', [name, values])
  }

  async addSheetRow(name: string, table: number, row: Omit<SheetRow, 'key'>): Promise<void> {
    let at = await this.sheetBook(name)
    if (!at) {
      await this.saveSheet((await this.listSheets()).find((s) => s.name === name)!) // its tab went missing: make it again
      at = (await this.sheetBook(name))!
    }
    const vals = await this.g.read(at.book.id, [at.ranges[table]], 'UNFORMATTED_VALUE')
    await this.g.write(at.book.id, await py<Plan['data']>('custom_add', [name, table, vals[0], row]), 'USER_ENTERED')
  }

  private async sheetValues(name: string) {
    const at = await this.sheetBook(name)
    if (!at) throw new Error('That sheet has no tab yet.')
    const vals = await this.g.read(at.book.id, at.ranges, 'FORMULA')
    return { at, values: Object.fromEntries(at.ranges.map((r, i) => [r, vals[i]])) }
  }

  async editSheetRow(name: string, key: string, fields: Partial<Omit<SheetRow, 'key'>>): Promise<void> {
    const { at, values } = await this.sheetValues(name)
    const data = await py<Plan['data']>('custom_edit', [name, values, key, fields])
    if (!data.length) throw new Error('That row is no longer in the sheet. Reload and try again.')
    await this.g.write(at.book.id, data, 'USER_ENTERED')
  }

  async deleteSheetRow(name: string, key: string): Promise<void> {
    const { at, values } = await this.sheetValues(name)
    const requests = await py<object[]>('custom_remove', [name, at.sheetId, values, key])
    if (!requests.length) throw new Error('That row is no longer in the sheet. Reload and try again.')
    await this.g.batch(at.book.id, requests)
  }

  private async ensureSettingsTab(id: string, title: string, header: string[]): Promise<void> {
    if ((await this.g.tabs(id)).some((t) => t.title === title)) return
    await this.g.batch(id, [{ addSheet: { properties: { title, gridProperties: { rowCount: 200, columnCount: header.length } } } }])
    await this.g.write(id, [{ range: `${quote(title)}!A1`, values: [header] }], 'RAW')
  }

  /** Settings tabs to read: a Settings sheet made before a tab existed (Reviewed) just lacks it. */
  private async settingsTabs(id: string): Promise<string[]> {
    const have = new Set((await this.g.tabs(id)).map((t) => t.title))
    return Object.keys(SETTINGS_RANGES).filter((n) => have.has(n))
  }

  async keepAsIs(key: string): Promise<void> {
    const at = this.cardsAt.get(key)
    if (!at) throw new Error('That card was already closed. Reload to see what is left.')
    const id = await this.settingsBook()
    if (!(await this.g.tabs(id)).some((t) => t.title === 'Reviewed')) {
      await this.g.batch(id, [{ addSheet: { properties: { title: 'Reviewed', gridProperties: { rowCount: 500, columnCount: 4 } } } }])
      await this.g.write(id, [{ range: "'Reviewed'!A1", values: [['Key', 'Date', 'Amount (RM)', 'Statement']] }], 'RAW')
    }
    // Remembered first, so a later upload doesn't open the card again.
    await this.g.append(id, "'Reviewed'!A:D", [await py<unknown[]>('reviewed_row', [key, at.card])])
    await this.removeCard(at.book, key)
    writeLater(readLater().filter((k) => k !== key))
  }

  async skipCard(key: string): Promise<void> {
    writeLater([...readLater().filter((k) => k !== key), key])
  }

  async notMine(key: string): Promise<void> {
    const at = this.cardsAt.get(key) ?? this.rowsAt.get(key)
    if (!at) throw new Error('That row is no longer in the sheet. Reload and try again.')
    const { values, ids } = await this.bookValues(at.book)
    const card = this.cardsAt.get(key)?.card
    const plan = await py<{ requests: object[]; removed: unknown[] }>('remove_row', [key, values, ids, card ?? null])
    // Remember it first, so a later upload never brings it back.
    await this.g.append(await this.settingsBook(), "'Removed'!A:D", [plan.removed])
    await this.g.batch(at.book.id, plan.requests)
    if (card) await this.removeCard(at.book, key)
  }

  private async removeCard(book: Book, key: string): Promise<void> {
    const [keys] = await this.g.read(book.id, [`${quote(TO_UPDATE)}!H2:H`], 'UNFORMATTED_VALUE')
    const i = keys.findIndex((r) => s(r[0]) === key)
    if (i >= 0) {
      const { ids } = await this.ids(book.id)
      await this.g.batch(book.id, [await py<object>('remove_card', [ids[TO_UPDATE], i + 2])])
    }
    this.cardsAt.delete(key)
  }

  // ---- upload ---------------------------------------------------------------------------

  async uploadStatements(all: UploadFile[], typed: Passwords = {}, onProgress?: (p: UploadProgress) => void): Promise<UploadResult[]> {
    // Accounts workbooks you kept by hand (.xlsx) are copied in as they are; the rest are statements.
    const workbooks = all.filter((f) => /\.xlsx$/i.test(f.name))
    const files = all.filter((f) => !workbooks.includes(f))
    // Each workbook is one part of the bar, the statements together another.
    const parts = workbooks.length + (files.length ? 1 : 0)
    let part = 0
    const tell: Tell = (fraction, step) => onProgress?.({ fraction: Math.min(1, (part + fraction) / parts), step })
    const imported: UploadResult[] = []
    for (const w of workbooks) {
      imported.push(await this.importWorkbook(w, tell))
      part++
    }
    if (!files.length) return imported
    const read = await this.uploadFiles(files, typed, tell)
    tell(1, 'Done')
    return [...imported, ...read]
  }

  /** An old accounts workbook: each month tab's rows onto the same month here, as rows you added. */
  private async importWorkbook(file: UploadFile, tell: Tell): Promise<UploadResult> {
    try {
      tell(0, `Reading ${file.name}`)
      await this.useSettings()
      type OldTrip = { name: string; currencies: { code: string; rate: number | null }[]; start: string; end: string;
        year: number; rm: object[]; paid: object[]; cash: Record<string, object[]>; received: object[] }
      type OldSheet = { name: string; year: number; counts: CustomSheet['counts'];
        tables: (CustomSheet['tables'][number] & { rows: object[] })[] }
      // Months your statements already cover aren't copied (they'd be counted twice).
      const { ledger } = await this.readSettings()
      const months = ledger.slice(1).map((r) => s(r[0]).slice(0, 7)).filter((m) => /^\d{4}-\d{2}$/.test(m)).sort()
      const out = await py<{ months: Record<string, object[]>; years: Record<string, number>; trips: OldTrip[];
        sheets: OldSheet[]; skipped: string[] }>('old_accounts', [null, months[0] ?? ''], [{ name: file.name, data: file.data }])
      const titles = Object.keys(out.months)
      if (!titles.length && !out.trips.length && !out.sheets.length) {
        return { file: file.name, status: 'failed', message: 'No month tabs (like "September 2022") with Date / Item / Amount columns found.' }
      }
      let added = 0
      let total = 0
      const steps = titles.length + out.trips.length + out.sheets.length
      let step = 0
      const stepAt = (what: string) => tell(0.05 + 0.95 * (step++ / Math.max(1, steps)), `${file.name}: ${what}`)
      for (const t of titles) {
        stepAt(t)
        added += await this.placeRowsCounted(out.years[t], out.months[t], t)
        total += out.months[t].length
      }
      const parts = titles.length ? [titles.length === 1 ? titles[0] : `${titles.length} months`] : []

      // Trips: added to Settings › Trips (which makes the tab), then all three blocks.
      for (const trip of out.trips) {
        stepAt(trip.name)
        const st = await this.getSettings()
        if (!st.trips.some((t) => t.name === trip.name)) {
          st.trips.push({ name: trip.name, start: trip.start, end: trip.end,
            currencies: trip.currencies.map((c) => ({ code: c.code, rate: c.rate ?? undefined })), match: [] })
          await this.saveSettings(st)
        }
        added += await this.placeRowsCounted(trip.year, trip.rm, trip.name)
        total += trip.rm.length + trip.paid.length + trip.received.length +
          Object.values(trip.cash).reduce((n, rows) => n + rows.length, 0)
        const book = (await this.book(trip.year))!
        const specs = await py<{ range: string }[]>('trip_extra_ranges', [trip.name])
        const now = await this.g.read(book.id, specs.map((x) => x.range), 'UNFORMATTED_VALUE')
        const data = await py<Plan['data']>('trip_extras', [trip.name, now, trip.paid, trip.cash, trip.received])
        if (data.length) await this.g.write(book.id, data, 'USER_ENTERED')
        added += data.reduce((n, d) => n + d.values.length, 0)
        parts.push(trip.name)
      }

      // Your own tabs (e.g. ang pao): a sheet in the Sheets section, then its rows.
      for (const sh of out.sheets) {
        stepAt(sh.name)
        if (!(await this.listSheets()).some((s) => s.name === sh.name)) {
          await this.saveSheet({ name: sh.name, year: sh.year, counts: sh.counts,
            tables: sh.tables.map((t) => ({ name: t.name, currency: t.currency, label: t.label })) })
        }
        const at = (await this.sheetBook(sh.name))!
        const vals = await this.g.read(at.book.id, at.ranges, 'UNFORMATTED_VALUE')
        for (const [i, t] of sh.tables.entries()) {
          total += t.rows.length
          const data = await py<Plan['data']>('custom_add_many', [sh.name, i, vals[i] ?? [], t.rows])
          if (data.length) await this.g.write(at.book.id, data, 'USER_ENTERED')
          added += data.reduce((n, d) => n + d.values.length, 0)
        }
        parts.push(`${sh.name} (Sheets)`)
      }
      const left = out.skipped.length ? ` Left out (your statements cover them): ${out.skipped.join(', ')}.` : ''
      return {
        file: file.name, status: 'ok', source: 'workbook', rowsAdded: added,
        message: `${added} of ${total} rows copied into ${parts.join(', ')}${added < total ? ' (the rest were already there)' : ''}.${left}`,
      }
    } catch (e) {
      return { file: file.name, status: 'failed', message: e instanceof Error ? e.message : String(e) }
    }
  }

  private async uploadFiles(files: UploadFile[], typed: Passwords, tell: Tell): Promise<UploadResult[]> {
    tell(0, `Reading ${files.length === 1 ? files[0].name : `${files.length} statements`}`)
    const settings = await this.readSettings()
    const saved = (await this.vaultState()) === 'unlocked' ? { ...this.unlocked!.passwords } : {}
    const passwords = { ...saved, ...typed }
    const out = await py<CompileOut>('compile_upload', [null, settings.values, passwords, settings.ledger, this.me()],
      files.map((f) => ({ name: f.name, data: f.data })))

    const okFiles = out.files.filter((f) => f.ok)
    if (okFiles.length) {
      // Typed passwords that opened a PDF are saved for next time.
      const learned = { ...saved }
      let changed = false
      for (const f of okFiles) if (typed[f.parser] && typed[f.parser] !== saved[f.parser]) {
        learned[f.parser] = typed[f.parser]
        changed = true
      }
      if (changed && this.unlocked) await this.savePasswords(learned)
      tell(0.3, 'Saving to your Ledger')
      await this.writeLedger(settings.id, out.ledger)
      for (const [i, year] of out.years.entries()) {
        tell(0.4 + 0.5 * (i / out.years.length), `Writing ${year} Accounts`)
        await this.syncYear(year)
      }
      if (await this.getKeepPdfCopies()) {
        tell(0.92, 'Keeping copies in Drive')
        await this.keepCopies(files.flatMap((f) => {
          const o = okFiles.find((x) => x.name === f.name)
          return o ? [{ file: f, parser: o.parser }] : []
        }))
      }
    }

    const tail = okFiles.length
      ? ` ${out.pairs} transfer(s) between your accounts paired; ${out.toUpdate} transaction(s) to update.`
      : ''
    return out.files.map((f): UploadResult => {
      if (f.ok) return { file: f.name, status: 'ok', source: f.parser, rowsAdded: f.count, message: `${f.count} transactions read.${tail}` }
      if (f.needs_password) {
        const tried = !!passwords[f.needs_password]
        return {
          file: f.name, status: 'password', source: f.needs_password, passwordFor: f.needs_password, wrongPassword: tried,
          message: tried ? 'The saved password did not open this PDF.' : 'This PDF needs a password.',
        }
      }
      return { file: f.name, status: 'failed', source: f.parser || undefined, message: f.error }
    })
  }

  private async writeLedger(settingsId: string, rows: Values): Promise<void> {
    const { ids } = await this.ids(settingsId)
    await this.g.batch(settingsId, [{
      updateSheetProperties: {
        properties: { sheetId: ids['Ledger'], gridProperties: { rowCount: rows.length + 200, columnCount: 14 } },
        fields: 'gridProperties.rowCount,gridProperties.columnCount',
      },
    }])
    await this.g.clear(settingsId, [LEDGER_RANGE])
    await this.g.write(settingsId, [{ range: "'Ledger'!A1", values: rows }], 'RAW')
  }

  private async syncYear(year: number): Promise<void> {
    await this.syncBook(year, (titles, created) => py<Prep>('prepare_year', [year, titles, created]),
      (ids, values) => py<Fin>('finish_year', [year, ids, values]))
  }

  /** Put rows (or none: just make the tab) on a month or trip tab, without touching To Update. */
  private async placeRows(year: number, rows: object[], target: string): Promise<Book> {
    return (await this.placeRowsWith(year, rows, target)).book
  }

  private async placeRowsCounted(year: number, rows: object[], target: string): Promise<number> {
    return (await this.placeRowsWith(year, rows, target)).added
  }

  private async placeRowsWith(year: number, rows: object[], target: string): Promise<{ book: Book; added: number }> {
    let added = 0
    const book = await this.syncBook(year, (titles, created) => py<Prep>('prepare_rows', [year, titles, rows, target, created]),
      async (ids, values) => {
        const fin = await py<Fin & { added: number }>('finish_rows', [year, ids, values])
        added = fin.added
        return fin
      })
    return { book, added }
  }

  /** One sync at a time: Python keeps the prepared plan between prepare and finish. */
  private syncing: Promise<unknown> = Promise.resolve()

  private syncBook(
    year: number,
    prepare: (titles: string[], created: boolean) => Promise<Prep>,
    finish: (ids: Record<string, number>, values: Record<string, Values>) => Promise<Fin>,
  ): Promise<Book> {
    const next = this.syncing.then(() => this.syncBookNow(year, prepare, finish))
    this.syncing = next.catch(() => undefined)
    return next
  }

  private async syncBookNow(
    year: number,
    prepare: (titles: string[], created: boolean) => Promise<Prep>,
    finish: (ids: Record<string, number>, values: Record<string, Values>) => Promise<Fin>,
  ): Promise<Book> {
    const title = await py<string>('spreadsheet_title', [year])
    let book = await this.book(year)
    let created = false
    if (!book) {
      book = { year, id: await this.g.createSpreadsheet(title) }
      created = true
      this.books = [...(this.books ?? []), book].sort((a, b) => a.year - b.year)
    }
    let tabs = await this.g.tabs(book.id)
    const prep = await prepare(tabs.map((t) => t.title), created)
    // Trip tabs made before they had this many currencies get wider first.
    const widen = tabs.filter((t) => (prep.widths?.[t.title] ?? 0) > (t.gridProperties?.columnCount ?? 0))
    const changed = prep.add.length + prep.delete.length > 0
    await this.g.batch(book.id, [
      ...widen.map((t) => ({ updateSheetProperties: {
        properties: { sheetId: t.sheetId, gridProperties: { columnCount: prep.widths![t.title] } },
        fields: 'gridProperties.columnCount' } })),
      ...prep.add.map((a) => ({
        addSheet: { properties: { title: a.title, index: a.index, gridProperties: { rowCount: a.rows, columnCount: a.cols } } },
      })),
      ...prep.delete.map((t) => ({ deleteSheet: { sheetId: tabs.find((x) => x.title === t)!.sheetId } })),
    ])
    if (changed) tabs = await this.g.tabs(book.id)
    const vals = await this.g.read(book.id, prep.reads, 'FORMULA')
    const values = Object.fromEntries(prep.reads.map((r, i) => [r, vals[i]]))
    const fin = await finish(Object.fromEntries(tabs.map((t) => [t.title, t.sheetId])), values)
    await this.run(book.id, fin)
    return book
  }

  // ---- rows by hand: add, move to / from a trip --------------------------------------

  async addRow(row: NewRow): Promise<void> {
    await this.useSettings()
    const target = await py<Target>('place_target', [row.trip ?? '', row.date])
    const fields = {
      kind: row.kind, date: row.date, item: row.item.trim(), amount: row.amount, category: row.category ?? '',
      importance: row.importance ?? '', source: row.source?.trim() ?? '', remarks: row.remarks?.trim() ?? '', key: newKey(),
    }
    if (target.trip && (row.kind === 'earn' || row.currency)) {
      // Money in on a trip is "paid back to you"; spending in a foreign currency goes in its block.
      const book = await this.placeRows(target.year, [], target.title) // make sure the trip tab exists
      const [ranges, fn, args] = row.kind === 'earn'
        ? [await py<string[]>('paid_ranges', [target.title]), 'paid_row', [] as unknown[]]
        : [await py<string[]>('cash_ranges', [target.title, row.currency]), 'cash_row', [row.currency]]
      const [vals] = await this.g.read(book.id, ranges, 'UNFORMATTED_VALUE')
      await this.g.write(book.id, await py<Plan['data']>(fn, [vals, target.title, fields, ...args]), 'USER_ENTERED')
      return
    }
    await this.placeRows(target.year, [fields], target.title)
  }

  async moveRow(key: string, trip: string | null): Promise<void> {
    for (const b of await this.yearBooks()) {
      const { values, ids } = await this.bookValues(b)
      const taken = await py<{ row: { date: string } | null; requests: object[] }>('take_row', [key, values, ids])
      if (!taken.row) continue
      const target = await py<Target>('place_target', [trip ?? '', taken.row.date])
      await this.g.batch(b.id, taken.requests)
      await this.placeRows(target.year, [taken.row], target.title)
      this.rowsAt.delete(key)
      return
    }
    throw new Error('That row is no longer in the sheet. Reload and try again.')
  }

  /** Copies of the PDFs in Drive › fincomp › statements › <bank> (best effort). */
  private async keepCopies(files: { file: UploadFile; parser: string }[]): Promise<void> {
    try {
      const root = await this.g.folder('statements', await this.g.folder('fincomp'))
      const folders = new Map<string, string>()
      for (const { file, parser } of files) {
        const name = COPY_FOLDERS[parser] ?? 'Other'
        if (!folders.has(name)) folders.set(name, await this.g.folder(name, root))
        await this.g.putFile(folders.get(name)!, file.name, 'application/pdf', file.data)
      }
    } catch {
      /* the accounts are already written; a missing copy isn't worth failing over */
    }
  }

  async getKeepPdfCopies(): Promise<boolean> {
    return !!(await this.g.readAppData<{ keepPdfCopies?: boolean }>(PREFS_FILE, {})).keepPdfCopies
  }

  async setKeepPdfCopies(on: boolean): Promise<void> {
    const prefs = await this.g.readAppData<Record<string, unknown>>(PREFS_FILE, {})
    await this.g.writeAppData(PREFS_FILE, { ...prefs, keepPdfCopies: on })
  }

  // ---- categories ---------------------------------------------------------------------

  private cats?: string[]
  private history?: string[][]

  async listCategories(): Promise<string[]> {
    if (this.cats) return this.cats
    const [lists] = await this.g.read(await this.settingsBook(), [SETTINGS_RANGES.Lists], 'UNFORMATTED_VALUE')
    this.cats = await py<string[]>('categories', [{ Lists: lists }])
    return this.cats
  }

  async saveCategories(names: string[]): Promise<void> {
    const id = await this.settingsBook()
    const [lists, trips] = await this.g.read(id, [SETTINGS_RANGES.Lists, SETTINGS_RANGES.Trips], 'UNFORMATTED_VALUE')
    const rows = await py<Values>('lists_rows', [names, { Lists: lists }])
    await this.g.clear(id, ["'Lists'!A2:B"])
    if (rows.length) await this.g.write(id, [{ range: "'Lists'!A2", values: rows }], 'RAW')
    this.cats = undefined
    // Every month tab's "By Category" block and the Category dropdowns.
    const settings = { Lists: [lists[0] ?? ['Categories', 'Importance'], ...rows], Trips: trips }
    for (const b of await this.yearBooks()) {
      const { ids } = await this.ids(b.id)
      const plan = await py<{ clear: string[]; data: { range: string; values: unknown[][] }[]; requests: object[] }>(
        'category_refresh', [b.year, ids, settings])
      if (plan.clear.length) await this.g.clear(b.id, plan.clear)
      if (plan.data.length) await this.g.write(b.id, plan.data, 'USER_ENTERED')
      if (plan.requests.length) await this.g.batch(b.id, plan.requests)
    }
  }

  async suggestCategories(cardKey: string, item: string): Promise<string[]> {
    const card = this.cardsAt.get(cardKey)?.card
    if (!card || card.kind !== 'spend') return []
    return py<string[]>('suggest', [card.statement, card.remarks, item || card.item, await this.categoryHistory(),
      await this.listCategories()])
  }

  /** [item, remarks, category] of every spending row that has a category, all years. */
  private async categoryHistory(): Promise<string[][]> {
    if (this.history) return this.history
    const out: string[][] = []
    for (const b of await this.yearBooks()) {
      const tabs = (await this.g.tabs(b.id)).map((t) => t.title).filter((t) => t !== TO_UPDATE && t !== 'Year End Summary')
      if (!tabs.length) continue
      const got = await this.g.read(b.id, tabs.map((t) => `${quote(t)}!A3:G`), 'UNFORMATTED_VALUE')
      for (const rows of got) for (const r of rows) if (s(r[2])) out.push([s(r[1]), s(r[6]), s(r[2])])
    }
    this.history = out
    return out
  }

  // ---- settings & passwords -------------------------------------------------------------

  async getSettings(): Promise<Settings> {
    const { values } = await this.readSettings()
    const body = (tab: string) => (values[tab] ?? []).slice(1).filter((r) => r.some((c) => s(c)))
    return {
      rules: body('Rules').map((r): Rule => ({
        match: s(r[0]), category: s(r[1]) as Category | '', importance: s(r[2]) as Importance | '',
        item: s(r[3]) || undefined, trip: s(r[4]) || undefined, skip: /^(true|yes|y|1)$/i.test(s(r[5])) || undefined,
        source: s(r[6]) || undefined,
      })),
      people: body('People').map((r) => ({ statementName: s(r[0]), shownAs: s(r[1]) })),
      trips: body('Trips').map((r) => ({
        name: s(r[0]), start: s(r[1]), end: s(r[2]),
        currencies: s(r[3]).split(',').map((c, i) => ({ code: c.trim(), rate: Number(s(r[4]).split(',')[i]) || undefined }))
          .filter((c) => c.code),
        match: s(r[5]).split('|').map((m) => m.trim()).filter(Boolean),
        link: s(r[6]) || undefined,
      })),
      ownPayees: body('Own payees').map((r) => s(r[0])),
    }
  }

  async saveSettings(st: Settings): Promise<void> {
    const id = await this.settingsBook()
    const tabs: Record<string, unknown[][]> = {
      Rules: st.rules.map((r) => [r.match, r.category ?? '', r.importance ?? '', r.item ?? '', r.trip ?? '', r.skip ? 'TRUE' : '', r.source ?? '', '']),
      People: st.people.map((p) => [p.statementName, p.shownAs]),
      Trips: st.trips.map((t) => [t.name, t.start, t.end, t.currencies.map((c) => c.code).join(', '),
        t.currencies.map((c) => c.rate ?? '').join(', '), t.match.join(' | '), t.link ?? '', 180]),
      'Own payees': st.ownPayees.map((p) => [p]),
    }
    // Headers stay; everything under them is replaced.
    await this.g.clear(id, Object.keys(tabs).map((t) => SETTINGS_RANGES[t].replace('A1:', 'A2:')))
    await this.g.write(id, Object.entries(tabs).filter(([, rows]) => rows.length).map(([t, rows]) => ({ range: `${quote(t)}!A2`, values: rows })), 'RAW')

    // Trips: existing trip tabs pick up a new currency / rate, and a new trip gets its tab now.
    await this.useSettings(true)
    for (const b of await this.yearBooks()) {
      const { ids } = await this.ids(b.id)
      const plan = await py<{ data: Plan['data']; requests: object[] }>('trip_refresh', [ids])
      await this.run(b.id, { clear: [], ...plan })
    }
    for (const t of st.trips) {
      const year = Number(t.start.slice(0, 4))
      const book = await this.book(year)
      if (!book || !(await this.g.tabs(book.id)).some((x) => x.title === t.name)) await this.placeRows(year, [], t.name)
    }
  }

  // ---- passwords: encrypted with the PIN (vault.ts) -----------------------------------

  private unlocked?: { key: CryptoKey; salt: string; passwords: Passwords }

  /** The encrypted blob: Drive first (it syncs devices), this device's copy if offline. */
  private async blob(): Promise<VaultBlob | null> {
    try {
      const b = await this.g.readAppData<VaultBlob | null>(VAULT_FILE, null)
      if (b) keepLocal(b)
      return b
    } catch {
      return localBlob()
    }
  }

  async vaultState(): Promise<VaultState> {
    const b = await this.blob()
    if (!b) return 'new'
    if (this.unlocked?.salt === b.salt) {
      this.unlocked.passwords = await vault.open(b, this.unlocked.key) // pick up edits from other devices
      return 'unlocked'
    }
    const key = await vault.rememberedKey(b.salt)
    if (key) {
      try {
        this.unlocked = { key, salt: b.salt, passwords: await vault.open(b, key) }
        return 'unlocked'
      } catch {
        await vault.forget()
      }
    }
    this.unlocked = undefined
    return 'locked'
  }

  async unlockVault(pin: string, rememberHere: boolean): Promise<void> {
    const b = await this.blob()
    if (!b) throw new Error('No saved passwords yet: set a PIN first.')
    const key = await vault.deriveKey(pin, vault.saltOf(b), b.iterations)
    this.unlocked = { key, salt: b.salt, passwords: await vault.open(b, key) } // throws WrongPinError
    if (rememberHere) await vault.remember(key, b.salt)
    else await vault.forget()
  }

  async setVaultPin(pin: string, rememberHere: boolean): Promise<void> {
    if (pin.length < 6) throw new Error('Use at least 6 characters for the PIN.')
    const existing = await this.blob()
    if (existing && !this.unlocked) throw new Error('Unlock with your current PIN first.')
    // What to encrypt: the current passwords, or the old unencrypted file once.
    const passwords = this.unlocked?.passwords ?? (await this.g.readAppData<Passwords>(LEGACY_PASSWORDS_FILE, {}))
    const salt = vault.newSalt() // a new random salt for every PIN
    const key = await vault.deriveKey(pin, salt)
    const b = await vault.seal(passwords, key, salt)
    await this.g.writeAppData(VAULT_FILE, b)
    keepLocal(b)
    await this.g.deleteAppData(LEGACY_PASSWORDS_FILE) // no readable copy left in Drive
    this.unlocked = { key, salt: b.salt, passwords }
    if (rememberHere) await vault.remember(key, b.salt)
    else await vault.forget()
  }

  async lockVault(): Promise<void> {
    this.unlocked = undefined
    await vault.forget()
  }

  async getPasswords(): Promise<Passwords> {
    if ((await this.vaultState()) !== 'unlocked') throw new Error('Your saved passwords are locked: enter your PIN.')
    return { ...this.unlocked!.passwords }
  }

  async savePasswords(passwords: Passwords): Promise<void> {
    if (!this.unlocked) throw new Error('Your saved passwords are locked: enter your PIN.')
    const clean = Object.fromEntries(Object.entries(passwords).filter(([, v]) => v))
    const b = await vault.seal(clean, this.unlocked.key, vault.saltOf({ salt: this.unlocked.salt } as VaultBlob))
    await this.g.writeAppData(VAULT_FILE, b)
    keepLocal(b)
    this.unlocked.passwords = clean
  }
}

function closes(card: Card): boolean {
  const purposeDone = !card.needs.includes('purpose') || !['Transfer', 'QR payment'].includes(card.item)
  const categoryDone = !card.needs.includes('category') || card.category !== ''
  return purposeDone && categoryDone
}

function readLater(): string[] {
  try {
    return JSON.parse(localStorage.getItem(LATER_KEY) ?? '[]')
  } catch {
    return []
  }
}

function writeLater(keys: string[]): void {
  try {
    localStorage.setItem(LATER_KEY, JSON.stringify(keys))
  } catch {
    /* storage blocked: "Later" order lasts this visit only */
  }
}

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
  type Category,
  type Importance,
  type Month,
  type MonthSummary,
  type Passwords,
  type Row,
  type RowEdit,
  type Rule,
  type Settings,
  type UploadFile,
  type UploadResult,
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
  Lists: "'Lists'!A1:B", Removed: "'Removed'!A1:D",
}
const LEDGER_RANGE = "'Ledger'!A1:M"
const LATER_KEY = 'fincomp.later'

interface FileOut { name: string; source: string; parser: string; count: number; error: string; needs_password: string; ok: boolean }
interface CompileOut { files: FileOut[]; ledger: Values; years: number[]; pairs: number; duplicates: number; toUpdate: number }
interface Prep { add: { title: string; index: number; rows: number; cols: number }[]; delete: string[]; reads: string[] }
interface Fin { clear: string[]; data: { range: string; values: unknown[][] }[]; requests: object[]; added: number; already: number; toUpdate: number }
interface PyCard { row: number; date: string | null; amount: number; who: string; statement: string; recordedAs: string; needsPurpose: boolean; needsCategory: boolean; tab: string; key: string }
interface PyRow { kind: 'spend' | 'earn'; row: number; date: string | null; item: string; category: string; amount: number; importance: string; remarks: string; key: string }
interface Book { year: number; id: string }
interface Where { book: Book; tab: string; trip: boolean }

const monthTitle = (y: number, m: number) => `${MONTHS[m - 1]} ${y}`
const quote = (t: string) => `'${t.replace(/'/g, "''")}'`
const isMonthTab = (t: string) => new RegExp(`^(${MONTHS.join('|')}) \\d{4}$`).test(t)
const s = (v: unknown) => (v === undefined || v === null ? '' : String(v).trim())

export class PyodideBackend implements Backend {
  private g: Google
  private settingsId?: string
  private books?: Book[]
  private rowsAt = new Map<string, Where>()
  private cardsAt = new Map<string, Where & { card: Card }>()

  constructor(auth: Auth) {
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
    if (this.books) return this.books
    const files = await this.g.findSpreadsheets(' Accounts')
    this.books = files
      .map((f) => ({ id: f.id, m: /^(\d{4}) Accounts$/.exec(f.name) }))
      .filter((f) => f.m)
      .map((f) => ({ year: +f.m![1], id: f.id }))
      .sort((a, b) => a.year - b.year)
    return this.books
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
    const names = Object.keys(SETTINGS_RANGES)
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
    const [[t5 = '']] = (await this.g.read(b.id, [`${quote(title)}!T5`], 'FORMULA')).map((v) => v[0] ?? [''])
    const names = [...String(t5).matchAll(/'((?:[^']|'')+)'!P8/g)].map((m) => m[1].replace(/''/g, "'"))
    const totalsByTrip = names.length ? await this.g.read(b.id, names.map((n) => `${quote(n)}!P8`), 'UNFORMATTED_VALUE') : []
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
        remarks: r.remarks, source: '',
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
    const ranges = await py<string[]>('tab_ranges', [where.tab, where.trip])
    const vals = await this.g.read(where.book.id, ranges, 'FORMULA')
    const values = Object.fromEntries(ranges.map((r, i) => [r, vals[i]]))
    const { ids } = await this.ids(where.book.id)
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

  async skipCard(key: string): Promise<void> {
    writeLater([...readLater().filter((k) => k !== key), key])
  }

  async notMine(key: string): Promise<void> {
    const at = this.cardsAt.get(key) ?? this.rowsAt.get(key)
    if (!at) throw new Error('That row is no longer in the sheet. Reload and try again.')
    const ranges = await py<string[]>('tab_ranges', [at.tab, at.trip])
    const vals = await this.g.read(at.book.id, ranges, 'FORMULA')
    const values = Object.fromEntries(ranges.map((r, i) => [r, vals[i]]))
    const { ids } = await this.ids(at.book.id)
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

  async uploadStatements(files: UploadFile[], typed: Passwords = {}): Promise<UploadResult[]> {
    const settings = await this.readSettings()
    const saved = (await this.vaultState()) === 'unlocked' ? { ...this.unlocked!.passwords } : {}
    const passwords = { ...saved, ...typed }
    const out = await py<CompileOut>('compile_upload', [null, settings.values, passwords, settings.ledger],
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
      await this.writeLedger(settings.id, out.ledger)
      for (const year of out.years) await this.syncYear(year)
      if (await this.getKeepPdfCopies()) {
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
    const title = await py<string>('spreadsheet_title', [year])
    let book = await this.book(year)
    let created = false
    if (!book) {
      book = { year, id: await this.g.createSpreadsheet(title) }
      created = true
      this.books = [...(this.books ?? []), book].sort((a, b) => a.year - b.year)
    }
    let tabs = await this.g.tabs(book.id)
    const prep = await py<Prep>('prepare_year', [year, tabs.map((t) => t.title), created])
    await this.g.batch(book.id, [
      ...prep.add.map((a) => ({
        addSheet: { properties: { title: a.title, index: a.index, gridProperties: { rowCount: a.rows, columnCount: a.cols } } },
      })),
      ...prep.delete.map((t) => ({ deleteSheet: { sheetId: tabs.find((x) => x.title === t)!.sheetId } })),
    ])
    tabs = await this.g.tabs(book.id)
    const vals = await this.g.read(book.id, prep.reads, 'FORMULA')
    const values = Object.fromEntries(prep.reads.map((r, i) => [r, vals[i]]))
    const fin = await py<Fin>('finish_year', [year, Object.fromEntries(tabs.map((t) => [t.title, t.sheetId])), values])
    await this.g.clear(book.id, fin.clear)
    await this.g.write(book.id, fin.data, 'USER_ENTERED')
    await this.g.batch(book.id, fin.requests)
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
      const got = await this.g.read(b.id, tabs.map((t) => `${quote(t)}!A3:F`), 'UNFORMATTED_VALUE')
      for (const rows of got) for (const r of rows) if (s(r[2])) out.push([s(r[1]), s(r[5]), s(r[2])])
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
        name: s(r[0]), start: s(r[1]), end: s(r[2]), currency: s(r[3]) || undefined,
        rate: s(r[4]) ? Number(r[4]) : undefined, match: s(r[5]).split('|').map((m) => m.trim()).filter(Boolean),
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
      Trips: st.trips.map((t) => [t.name, t.start, t.end, t.currency ?? '', t.rate ?? '', t.match.join(' | '), t.link ?? '', 180]),
      'Own payees': st.ownPayees.map((p) => [p]),
    }
    // Headers stay; everything under them is replaced.
    await this.g.clear(id, Object.keys(tabs).map((t) => SETTINGS_RANGES[t].replace('A1:', 'A2:')))
    await this.g.write(id, Object.entries(tabs).filter(([, rows]) => rows.length).map(([t, rows]) => ({ range: `${quote(t)}!A2`, values: rows })), 'RAW')
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

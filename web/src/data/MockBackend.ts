import {
  CATEGORIES,
  IMPORTANCE,
  STATEMENT_SOURCES,
  type Backend,
  type Card,
  type CardAnswer,
  type CustomSheet,
  type SheetRow,
  type SheetTableRows,
  type Month,
  type MonthSummary,
  type NewRow,
  type Passwords,
  type Row,
  type RowEdit,
  type Settings,
  type UploadFile,
  type UploadResult,
  type VaultState,
  type TripDetail,
  type TripTotal,
  type UploadProgress,
  type YearSummary,
} from './Backend'
import { WrongPinError } from './vault'
import { demoUploadRows, initialState, toRow, type MockState } from './mockData'

const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms))
const clone = <T,>(x: T): T => structuredClone(x)

/** Which parser a file name looks like, as the real `find_parser` would decide from its contents. */
function guessSource(name: string): string | undefined {
  const n = name.toLowerCase()
  if (n.includes('tng') || n.includes('transactions')) return 'tng'
  if (n.includes('aeon') && n.includes('credit')) return 'aeon_credit'
  if (n.includes('aeon')) return 'aeon'
  if (n.includes('maybank') && n.includes('card')) return 'maybank_cc'
  if (n.includes('maybank')) return 'maybank_sa'
  if (n.includes('gx')) return 'gx'
  if (n.includes('ryt')) return 'ryt'
  return undefined
}

/** Sources whose demo PDFs are "encrypted". */
const ENCRYPTED = new Set(['tng', 'aeon_credit', 'maybank_cc'])

/**
 * In-memory Backend with synthetic data so every screen works without
 * Google or Pyodide. State resets on reload.
 *
 * Demo upload behaviour: the file name picks the bank (e.g. "tng-oct.pdf",
 * "maybank.pdf"); a name without one fails. TNG / AEON Credit / Maybank card
 * files need a password; any password except "wrong" opens them.
 */
export class MockBackend implements Backend {
  private s: MockState = initialState()
  private cats: string[] = [...CATEGORIES]
  private keepCopies = false
  private sheets: CustomSheet[] = [{
    name: 'Chinese New Year', year: 2026, counts: 'earnings',
    tables: [{ name: 'Ang Pao (RM)', currency: 'RM', label: 'Person' }, { name: 'Ang Pao (SGD)', currency: 'SGD', label: 'Person' }],
    category: 'Chinese New Year',
  }, {
    name: 'New Years', year: 2025, counts: '', category: 'New Years',
    tables: [{ name: 'Ang Pao (RM)', currency: 'RM', label: 'Person' }],
  }, {
    name: 'Expected Monthly Spendings', year: 2025, counts: '',
    tables: [{ name: 'Expected Monthly Spendings', currency: 'RM', label: 'Item' }],
  }, {
    name: 'Unit Trusts', year: 2026, counts: '', category: 'Investments',
    tables: [{ name: 'Bought', currency: 'RM', label: 'Fund' }, { name: 'Dividends', currency: 'RM', label: 'Fund' }],
  }]
  private sheetData = new Map<string, SheetRow[][]>([['Chinese New Year', [
    [{ key: 's1', date: '2026-02-17', item: 'Auntie Mei', amount: 50, remarks: '' }, { key: 's2', date: '2026-02-17', item: 'Uncle Bob', amount: 100, remarks: 'Penang' }],
    [{ key: 's3', date: '2026-02-20', item: 'SG cousin', amount: 10, remarks: '' }],
  ]], ['Unit Trusts', [
    [{ key: 'u1', date: '2026-03-02', item: 'Global Equity Fund', amount: 500, remarks: 'Monthly top-up' }],
    [{ key: 'u2', date: '2026-06-30', item: 'Global Equity Fund', amount: 18.4, remarks: '' }],
  ]]])

  async listYears(): Promise<number[]> {
    await wait(50)
    return [...new Set(this.s.rows.map((r) => +r.date.slice(0, 4)))].sort()
  }

  async yearSummary(year: number): Promise<YearSummary> {
    const months: YearSummary['months'] = []
    const cats = new Map<string, number>()
    for (let m = 1; m <= 12; m++) {
      if (!this.s.rows.some((r) => r.date.startsWith(`${year}-${String(m).padStart(2, '0')}`))) continue
      const s = await this.monthSummary(year, m)
      months.push({ month: m, earnings: s.earnings, spendings: s.spendings, trips: s.tripsTotal, final: s.final })
      for (const c of s.byCategory) cats.set(c.name, (cats.get(c.name) ?? 0) + c.amount)
    }
    const total = (k: 'earnings' | 'spendings' | 'trips') => Math.round(months.reduce((a, m) => a + m[k], 0) * 100) / 100
    const [earnings, spendings, trips] = [total('earnings'), total('spendings'), total('trips')]
    return {
      year, months, earnings, spendings, trips, final: Math.round((earnings - spendings - trips) * 100) / 100,
      byCategory: [...cats].map(([name, amount]) => ({ name, amount })).filter((c) => c.amount > 0).sort((a, b) => b.amount - a.amount),
    }
  }

  async listTrips(): Promise<TripTotal[]> {
    await wait(100)
    return this.s.settings.trips
      .map((trip) => {
        const rows = this.s.rows.filter((r) => r.trip === trip.name)
        return { trip: clone(trip), year: +trip.start.slice(0, 4), total: rows.length ? sum(rows) : null }
      })
      .sort((a, b) => b.trip.start.localeCompare(a.trip.start))
  }

  async tripDetail(name: string): Promise<TripDetail> {
    await wait()
    const trip = this.s.settings.trips.find((t) => t.name === name)
    if (!trip) throw new Error(`No trip called "${name}" in Settings › Trips.`)
    const rows = this.s.rows.filter((r) => r.trip === name && r.kind === 'spend')
    const total = sum(rows)
    return {
      name, start: trip.start, end: trip.end, total, spentRm: total, paidBack: 0,
      rm: rows.map((r) => ({ date: r.date, item: r.item, amount: r.amount, category: r.category, importance: r.importance, source: r.source, remarks: r.remarks })),
      paid: [],
      currencies: trip.currencies.map((c) => ({ code: c.code, rate: c.rate, spent: 0, rm: 0, rows: [] })),
      received: [],
    }
  }

  async listSheets(): Promise<CustomSheet[]> {
    await wait(50)
    return clone(this.sheets)
  }

  async saveSheet(sheet: CustomSheet, previousName?: string): Promise<void> {
    await wait()
    const i = this.sheets.findIndex((s) => s.name === (previousName ?? sheet.name))
    if (i >= 0) this.sheets[i] = clone(sheet)
    else this.sheets.push(clone(sheet))
    const data = this.sheetData.get(previousName ?? sheet.name) ?? []
    this.sheetData.delete(previousName ?? sheet.name)
    this.sheetData.set(sheet.name, sheet.tables.map((_, t) => data[t] ?? []))
  }

  async sheetRows(name: string): Promise<SheetTableRows[]> {
    await wait(100)
    const sheet = this.sheets.find((s) => s.name === name)
    if (!sheet) throw new Error(`No sheet called "${name}".`)
    const data = this.sheetData.get(name) ?? []
    return sheet.tables.map((t, index) => {
      const rows = clone(data[index] ?? [])
      return { ...t, index, rows, total: Math.round(rows.reduce((a, r) => a + r.amount, 0) * 100) / 100 }
    })
  }

  async addSheetRow(name: string, table: number, row: Omit<SheetRow, 'key'>): Promise<void> {
    await wait()
    const data = this.sheetData.get(name) ?? []
    ;(data[table] ??= []).push({ ...row, key: `s-${Date.now()}` })
    this.sheetData.set(name, data)
  }

  async editSheetRow(name: string, key: string, fields: Partial<Omit<SheetRow, 'key'>>): Promise<void> {
    await wait()
    for (const rows of this.sheetData.get(name) ?? []) {
      const r = rows.find((x) => x.key === key)
      if (r) Object.assign(r, fields)
    }
  }

  async deleteSheetRow(name: string, key: string): Promise<void> {
    await wait()
    this.sheetData.set(name, (this.sheetData.get(name) ?? []).map((rows) => rows.filter((r) => r.key !== key)))
  }

  async deleteSheet(name: string): Promise<void> {
    await wait()
    this.sheets = this.sheets.filter((s) => s.name !== name)
    this.sheetData.delete(name)
  }

  async sheetLink(): Promise<string | null> {
    return null // no Google in the demo
  }

  async getKeepPdfCopies(): Promise<boolean> {
    return this.keepCopies
  }

  async setKeepPdfCopies(on: boolean): Promise<void> {
    await wait(100)
    this.keepCopies = on
  }

  async listCategories(): Promise<string[]> {
    await wait(50)
    return [...this.cats]
  }

  async saveCategories(names: string[]): Promise<void> {
    await wait()
    this.cats = [...new Set(names.map((n) => n.trim()).filter(Boolean))]
  }

  /** A rough stand-in for suggest.py: your past rows with the same person or Item. */
  async suggestCategories(cardKey: string, item: string): Promise<string[]> {
    await wait(50)
    const card = this.s.cards.get(cardKey)
    if (!card || card.kind !== 'spend') return []
    const it = (item || card.item).toLowerCase()
    const score = new Map<string, number>()
    for (const r of this.s.rows) {
      if (!r.category || !this.cats.includes(r.category)) continue
      const hit = (card.remarks && r.remarks === card.remarks ? 3 : 0) + (it && r.item.toLowerCase() === it ? 4 : 0)
      if (hit) score.set(r.category, (score.get(r.category) ?? 0) + hit)
    }
    return [...score].sort((a, b) => b[1] - a[1]).map(([c]) => c).slice(0, 3)
  }

  async listMonths(): Promise<Month[]> {
    await wait(100)
    const seen = new Set<string>()
    for (const r of this.s.rows) seen.add(r.date.slice(0, 7))
    return [...seen].sort().map((ym) => ({ year: +ym.slice(0, 4), month: +ym.slice(5, 7) }))
  }

  async monthSummary(year: number, month: number): Promise<MonthSummary> {
    await wait()
    const ym = `${year}-${String(month).padStart(2, '0')}`
    const inMonth = this.s.rows.filter((r) => r.date.startsWith(ym))
    const spend = inMonth.filter((r) => r.kind === 'spend' && !r.trip)
    const earnings = sum(inMonth.filter((r) => r.kind === 'earn'))
    const spendings = sum(spend)

    const trips = this.s.settings.trips
      .filter((t) => t.end.startsWith(ym))
      .map((t) => ({ name: t.name, total: sum(this.s.rows.filter((r) => r.trip === t.name)) }))
      .filter((t) => t.total > 0)
    const tripsTotal = trips.reduce((a, t) => a + t.total, 0)

    const byCategory = [...this.cats, ''].map((name) => ({
      name,
      amount: sum(spend.filter((r) => r.category === name)),
    }))
    const byImportance = [...IMPORTANCE, ''].map((name) => ({
      name: name as (typeof IMPORTANCE)[number] | '',
      amount: sum(spend.filter((r) => r.importance === name)),
    }))
    return {
      year,
      month,
      byCategory: byCategory.filter((c) => c.name !== '' || c.amount > 0),
      byImportance: byImportance.filter((c) => c.name !== '' || c.amount > 0),
      earnings,
      spendings,
      trips,
      tripsTotal,
      final: round(earnings - spendings - tripsTotal),
    }
  }

  async monthRows(year: number, month: number): Promise<Row[]> {
    await wait()
    const ym = `${year}-${String(month).padStart(2, '0')}`
    // Trip rows show in the month they ended, like the trip tab's total does.
    const tripEnd = new Map(this.s.settings.trips.map((t) => [t.name, t.end]))
    return clone(
      this.s.rows
        .filter((r) => (r.trip ? (tripEnd.get(r.trip) ?? r.date) : r.date).startsWith(ym))
        .sort((a, b) => a.date.localeCompare(b.date)),
    )
  }

  async editRow(key: string, fields: RowEdit): Promise<void> {
    await wait()
    const row = this.s.rows.find((r) => r.key === key)
    if (!row) throw new Error('That row is no longer in the sheet.')
    fields = Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== undefined)) as RowEdit
    Object.assign(row, fields)
    // Editing the month tab directly closes its card, as in the sheet.
    const card = this.s.cards.get(key)
    if (card) {
      Object.assign(card, fields)
      if (closes(card)) this.s.cards.delete(key)
    }
  }

  async addRow(row: NewRow): Promise<void> {
    await wait()
    this.s.rows.push({
      key: `m-${Date.now()}`, kind: row.kind, date: row.date, item: row.item.trim(), amount: row.amount,
      category: row.kind === 'spend' ? (row.category ?? '') : '', importance: row.kind === 'spend' ? (row.importance ?? '') : '',
      remarks: row.remarks ?? '', source: row.source ?? '', trip: row.kind === 'spend' ? row.trip || undefined : undefined,
    })
  }

  async deleteRow(key: string): Promise<void> {
    await wait()
    this.s.rows = this.s.rows.filter((r) => r.key !== key)
    this.s.cards.delete(key)
  }

  async moveRow(key: string, trip: string | null): Promise<void> {
    await wait()
    const row = this.s.rows.find((r) => r.key === key)
    if (!row) throw new Error('That row is no longer in the sheet.')
    row.trip = trip ?? undefined
  }

  async listCards(): Promise<Card[]> {
    await wait(150)
    const order = (c: Card) => (this.s.later.includes(c.key) ? 1 : 0)
    return clone(
      [...this.s.cards.values()].sort((a, b) => order(a) - order(b) || a.date.localeCompare(b.date)),
    )
  }

  async saveCard(key: string, answer: CardAnswer): Promise<void> {
    await wait()
    const card = this.s.cards.get(key)
    if (!card) throw new Error('That card was already closed.')
    const fields: RowEdit = {}
    if (answer.item) fields.item = answer.item
    if (answer.category !== undefined) fields.category = answer.category
    if (answer.importance !== undefined) fields.importance = answer.importance
    const row = this.s.rows.find((r) => r.key === key)
    if (row) Object.assign(row, fields)
    this.s.cards.delete(key)
    this.s.later = this.s.later.filter((k) => k !== key)

    if (answer.sameForEvery) {
      const match = card.counterparty || card.statement
      this.s.settings.rules.push({
        match,
        item: answer.item || undefined,
        category: answer.category || undefined,
        importance: answer.importance || undefined,
      })
      // The new rule answers the other open cards from the same payee/shop.
      for (const other of [...this.s.cards.values()]) {
        if ((other.counterparty || other.statement) !== match || other.kind !== card.kind) continue
        const r = this.s.rows.find((x) => x.key === other.key)
        if (r) Object.assign(r, fields)
        this.s.cards.delete(other.key)
      }
    }
  }

  async keepAsIs(key: string): Promise<void> {
    await wait()
    this.s.cards.delete(key)
    this.s.later = this.s.later.filter((k) => k !== key)
  }

  async skipCard(key: string): Promise<void> {
    await wait(100)
    this.s.later = [...this.s.later.filter((k) => k !== key), key]
  }

  async notMine(key: string): Promise<void> {
    await wait()
    this.s.cards.delete(key)
    this.s.rows = this.s.rows.filter((r) => r.key !== key)
  }

  async uploadStatements(files: UploadFile[], passwords: Passwords = {}, onProgress?: (p: UploadProgress) => void): Promise<UploadResult[]> {
    const results: UploadResult[] = []
    for (const [i, f] of files.entries()) {
      onProgress?.({ fraction: i / files.length, step: `Reading ${f.name}` })
      await wait(500)
      const source = guessSource(f.name)
      if (f.name.toLowerCase().endsWith('.xlsx')) {
        results.push({ file: f.name, status: 'ok', source: 'workbook', rowsAdded: 0, message: 'Accounts workbook: nothing to copy in the demo.' })
        continue
      }
      if (f.name.toLowerCase().endsWith('.csv')) {
        results.push({ file: f.name, status: 'ok', source: 'splitwise', rowsAdded: 0, message: 'Splitwise export: nothing to add in the demo.' })
        continue
      }
      if (!f.name.toLowerCase().endsWith('.pdf')) {
        results.push({ file: f.name, status: 'failed', message: 'Not a PDF or CSV.' })
        continue
      }
      if (!source) {
        results.push({ file: f.name, status: 'failed', message: "No parser recognises this statement (bank header not found)." })
        continue
      }
      if (ENCRYPTED.has(source)) {
        const typed = passwords[source]
        const pw = typed ?? (this.open ? this.s.passwords[source] : undefined)
        if (!pw || pw === 'wrong') {
          results.push({
            file: f.name,
            status: 'password',
            source,
            passwordFor: source,
            wrongPassword: !!pw,
            message: pw ? 'The password did not open this PDF.' : 'This PDF needs a password.',
          })
          continue
        }
        if (typed && this.open) this.s.passwords[source] = typed
      }
      if (this.s.uploaded.has(f.name)) {
        results.push({ file: f.name, status: 'ok', source, rowsAdded: 0, cardsAdded: 0, message: 'Already uploaded: nothing new.' })
        continue
      }
      this.s.uploaded.add(f.name)
      const label = STATEMENT_SOURCES.find((x) => x.key === source)?.label.split(' ')[0] ?? source
      let rows = 0
      let cards = 0
      for (const seed of demoUploadRows(source, label)) {
        const r = toRow(seed)
        const { needs, statement, counterparty, ...row } = r
        this.s.rows.push(row)
        rows += 1
        if (needs) {
          this.s.cards.set(row.key, { ...row, needs, statement: statement!, counterparty: counterparty! })
          cards += 1
        }
      }
      results.push({
        file: f.name,
        status: 'ok',
        source,
        rowsAdded: rows,
        cardsAdded: cards,
        message: `${rows} rows recorded, ${cards} to update. Pairs and dedupe checks passed.`,
      })
    }
    return results
  }

  async getSettings(): Promise<Settings> {
    await wait()
    return clone(this.s.settings)
  }

  async saveSettings(settings: Settings): Promise<void> {
    await wait()
    this.s.settings = clone(settings)
  }

  // Demo vault: same states and errors as the real one, PIN kept in memory.
  private pin: string | null = null
  private open = false

  async vaultState(): Promise<VaultState> {
    await wait(100)
    return this.pin === null ? 'new' : this.open ? 'unlocked' : 'locked'
  }

  async unlockVault(pin: string): Promise<void> {
    await wait(600) // the real one runs 600,000 PBKDF2 rounds
    if (pin !== this.pin) throw new WrongPinError()
    this.open = true
  }

  async setVaultPin(pin: string): Promise<void> {
    await wait(600)
    if (pin.length < 6) throw new Error('Use at least 6 characters for the PIN.')
    if (this.pin !== null && !this.open) throw new Error('Unlock with your current PIN first.')
    this.pin = pin
    this.open = true
  }

  async lockVault(): Promise<void> {
    this.open = false
  }

  async getPasswords(): Promise<Passwords> {
    await wait()
    if (!this.open) throw new Error('Your saved passwords are locked: enter your PIN.')
    return { ...this.s.passwords }
  }

  async savePasswords(passwords: Passwords): Promise<void> {
    await wait()
    if (!this.open) throw new Error('Your saved passwords are locked: enter your PIN.')
    this.s.passwords = { ...passwords }
  }
}

function sum(rows: Row[]): number {
  return round(rows.reduce((a, r) => a + r.amount, 0))
}

function round(n: number): number {
  return Math.round(n * 100) / 100
}

function closes(card: Card): boolean {
  const purposeDone = !card.needs.includes('purpose') || !['Transfer', 'QR payment'].includes(card.item)
  const categoryDone = !card.needs.includes('category') || card.category !== ''
  return purposeDone && categoryDone
}

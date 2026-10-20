import {
  CATEGORIES,
  IMPORTANCE,
  STATEMENT_SOURCES,
  type Backend,
  type Card,
  type CardAnswer,
  type Month,
  type MonthSummary,
  type Passwords,
  type Row,
  type RowEdit,
  type Settings,
  type UploadFile,
  type UploadResult,
  type VaultState,
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
    Object.assign(row, fields)
    // Editing the month tab directly closes its card, as in the sheet.
    const card = this.s.cards.get(key)
    if (card) {
      Object.assign(card, fields)
      if (closes(card)) this.s.cards.delete(key)
    }
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

  async skipCard(key: string): Promise<void> {
    await wait(100)
    this.s.later = [...this.s.later.filter((k) => k !== key), key]
  }

  async notMine(key: string): Promise<void> {
    await wait()
    this.s.cards.delete(key)
    this.s.rows = this.s.rows.filter((r) => r.key !== key)
  }

  async uploadStatements(files: UploadFile[], passwords: Passwords = {}): Promise<UploadResult[]> {
    const results: UploadResult[] = []
    for (const f of files) {
      await wait(500)
      const source = guessSource(f.name)
      if (!f.name.toLowerCase().endsWith('.pdf')) {
        results.push({ file: f.name, status: 'failed', message: 'Not a PDF.' })
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

// Synthetic demo data for MockBackend. Every name, shop and amount here is
// made up; never put real statement data in this file.
import type { Card, Category, Importance, Kind, Need, Passwords, Row, Settings } from './Backend'

let seq = 0
function key(source: string, date: string): string {
  seq += 1
  return `${source.toLowerCase()}:${date}:${String(seq).padStart(4, '0')}`
}

interface Seed {
  date: string
  kind?: Kind
  item: string
  amount: number
  category?: Category | ''
  importance?: Importance | ''
  remarks?: string
  source: string
  trip?: string
  /** Makes it a To Update card. */
  needs?: Need[]
  statement?: string
  counterparty?: string
}

const SEEDS: Seed[] = [
  // ---- September 2026 ----
  { date: '2026-09-01', kind: 'earn', item: 'Salary', amount: 5200, remarks: 'From Acme Widgets Sdn Bhd', source: 'Maybank' },
  { date: '2026-09-02', item: 'Electricity', amount: 142.3, category: 'Bills', importance: 'Essential', source: 'Maybank', statement: 'TNB BILL PAYMENT' },
  { date: '2026-09-02', item: 'Internet', amount: 139, category: 'Bills', importance: 'Essential', source: 'Maybank', statement: 'UNIFI HOME FIBRE' },
  { date: '2026-09-03', item: 'ZUS Coffee', amount: 12.9, category: 'Food', importance: 'Nice to Have', source: 'TNG', statement: 'ZUS COFFEE KLCC' },
  { date: '2026-09-04', item: 'Grab', amount: 18.5, category: 'Transport', importance: 'Essential', source: 'GX', statement: 'GRAB RIDES' },
  { date: '2026-09-05', item: 'Shopee', amount: 86.4, category: 'Shopping', importance: 'Have to Have', source: 'AEON Credit', statement: 'SHOPEE MALAYSIA' },
  { date: '2026-09-06', item: 'Petronas', amount: 60, category: 'Transport', importance: 'Essential', source: 'Maybank', statement: 'PETRONAS SS2' },
  { date: '2026-09-07', item: 'Transfer', amount: 45, remarks: 'To Jane Tan', source: 'TNG', needs: ['purpose', 'category'], statement: 'DuitNow Transfer JANE TAN', counterparty: 'JANE TAN' },
  { date: '2026-09-08', item: 'Dinner', amount: 64.2, category: 'Food', importance: 'Courtesy', remarks: 'To Bob Lim', source: 'AEON Bank' },
  { date: '2026-09-09', item: 'Netflix', amount: 55, category: 'Entertainment', importance: 'Nice to Have', source: 'AEON Credit', statement: 'NETFLIX.COM' },
  { date: '2026-09-10', item: 'QR payment', amount: 9.8, remarks: 'To Kedai Makan Ah Seng', source: 'TNG', needs: ['purpose', 'category'], statement: 'QR Payment KEDAI MAKAN AH SENG' },
  { date: '2026-09-11', item: 'Watsons', amount: 32.7, category: 'Health', importance: 'Have to Have', source: 'Ryt', statement: 'WATSONS MIDVALLEY' },
  { date: '2026-09-12', kind: 'earn', item: 'Transfer', amount: 120, remarks: 'From Bob Lim', source: 'AEON Bank', needs: ['purpose'], statement: 'DuitNow BOB LIM', counterparty: 'BOB LIM' },
  { date: '2026-09-13', item: 'Mr DIY', amount: 27.6, category: '', source: 'GX', needs: ['category'], statement: 'MR DIY SUNWAY' },
  { date: '2026-09-14', item: 'Udemy', amount: 54.9, category: 'Self-Development', importance: 'Nice to Have', source: 'AEON Credit', statement: 'UDEMY ONLINE' },
  { date: '2026-09-15', item: 'Ferry ticket', amount: 70, category: 'Transport', importance: 'Essential', source: 'TNG', trip: 'Penang Trip', statement: 'PENANG FERRY' },
  { date: '2026-09-15', item: 'Hotel', amount: 380, category: 'Bills', importance: 'Have to Have', source: 'AEON Credit', trip: 'Penang Trip', statement: 'AGODA *HOTEL' },
  { date: '2026-09-16', item: 'Char Kuey Teow', amount: 22, category: 'Food', importance: 'Nice to Have', source: 'TNG', trip: 'Penang Trip', statement: 'QR Payment HAWKER' },
  { date: '2026-09-18', item: '99 Speedmart', amount: 41.35, category: '', source: 'Maybank', needs: ['category'], statement: '99 SPEEDMART 1234' },
  { date: '2026-09-20', item: 'Transfer', amount: 300, remarks: 'To Siti Aminah', source: 'Maybank', needs: ['purpose', 'category'], statement: 'IBG TRANSFER SITI AMINAH', counterparty: 'SITI AMINAH' },
  { date: '2026-09-21', item: 'Clinic', amount: 85, category: 'Health', importance: 'Essential', source: 'Maybank', statement: 'KLINIK SEJAHTERA' },
  { date: '2026-09-22', kind: 'earn', item: 'GO+ earnings', amount: 6.42, remarks: '', source: 'TNG' },
  { date: '2026-09-24', item: 'Steam', amount: 39, category: 'Entertainment', importance: 'Regretted', source: 'Ryt', statement: 'STEAM PURCHASE' },
  { date: '2026-09-26', item: 'Transfer', amount: 25, remarks: 'To Jane Tan', source: 'GX', needs: ['purpose', 'category'], statement: 'DuitNow JANE TAN', counterparty: 'JANE TAN' },
  { date: '2026-09-28', kind: 'earn', item: 'Interest', amount: 3.18, remarks: '', source: 'Ryt' },
  { date: '2026-09-29', item: 'Birthday gift', amount: 150, category: 'Misc', importance: 'Courtesy', remarks: 'To Mei Ling Wong', source: 'AEON Bank' },
  // ---- October 2026 ----
  { date: '2026-10-01', kind: 'earn', item: 'Salary', amount: 5200, remarks: 'From Acme Widgets Sdn Bhd', source: 'Maybank' },
  { date: '2026-10-02', item: 'Electricity', amount: 128.9, category: 'Bills', importance: 'Essential', source: 'Maybank', statement: 'TNB BILL PAYMENT' },
  { date: '2026-10-03', item: 'Grab Food', amount: 31.4, category: 'Food', importance: 'Nice to Have', source: 'GX', statement: 'GRAB*FOOD' },
  { date: '2026-10-05', item: 'QR payment', amount: 15.5, remarks: 'To Nasi Lemak Corner', source: 'TNG', needs: ['purpose', 'category'], statement: 'QR Payment NASI LEMAK CORNER' },
  { date: '2026-10-06', item: 'Lazada', amount: 112, category: '', source: 'AEON Credit', needs: ['category'], statement: 'LAZADA MY' },
  { date: '2026-10-08', item: 'Parking', amount: 6, category: 'Transport', importance: 'Essential', source: 'TNG', statement: 'PARKING SUNWAY PYRAMID' },
  { date: '2026-10-09', kind: 'earn', item: 'Transfer', amount: 50, remarks: 'From Ahmad Rahman', source: 'GX', needs: ['purpose'], statement: 'DuitNow AHMAD RAHMAN', counterparty: 'AHMAD RAHMAN' },
  { date: '2026-10-10', item: 'Gym', amount: 99, category: 'Health', importance: 'Have to Have', source: 'Maybank', statement: 'ANYTIME FITNESS' },
  { date: '2026-10-12', item: 'Transfer', amount: 60, remarks: 'To Bob Lim', source: 'AEON Bank', needs: ['purpose', 'category'], statement: 'DuitNow BOB LIM', counterparty: 'BOB LIM' },
]

function toRow(s: Seed): Row & Partial<Card> {
  const k = key(s.source, s.date)
  const row: Row & Partial<Card> = {
    key: k,
    kind: s.kind ?? 'spend',
    date: s.date,
    item: s.item,
    amount: s.amount,
    category: s.category ?? '',
    importance: s.importance ?? '',
    remarks: s.remarks ?? '',
    source: s.source,
    trip: s.trip,
  }
  if (s.needs) {
    row.needs = s.needs
    row.statement = s.statement ?? s.item
    row.counterparty = s.counterparty ?? ''
  }
  return row
}

export interface MockState {
  rows: Row[]
  /** Open cards by row key. */
  cards: Map<string, Card>
  /** Keys pushed to the back by "Later". */
  later: string[]
  settings: Settings
  passwords: Passwords
  uploaded: Set<string>
}

export function initialState(): MockState {
  const rows: Row[] = []
  const cards = new Map<string, Card>()
  for (const s of SEEDS) {
    const r = toRow(s)
    const { needs, statement, counterparty, ...row } = r
    rows.push(row)
    if (needs) cards.set(row.key, { ...row, needs, statement: statement!, counterparty: counterparty! })
  }
  return {
    rows,
    cards,
    later: [],
    settings: {
      rules: [
        { match: 'GRAB*FOOD', category: 'Food' },
        { match: 'GRAB', category: 'Transport', importance: 'Essential' },
        { match: 'SHOPEE', category: 'Shopping' },
        { match: 'TNB', item: 'Electricity', category: 'Bills', importance: 'Essential' },
        { match: 'UNIFI', item: 'Internet', category: 'Bills', importance: 'Essential' },
        { match: 'NETFLIX', category: 'Entertainment', importance: 'Nice to Have' },
        { match: 'WATSONS', category: 'Health' },
        { match: 'CASHBACK', source: 'aeon_credit', skip: true },
      ],
      people: [
        { statementName: 'JANE TAN', shownAs: 'Jane Tan' },
        { statementName: 'BOB LIM', shownAs: 'Bob Lim' },
      ],
      trips: [
        { name: 'Penang Trip', start: '2026-09-15', end: '2026-09-17', match: ['AGODA', 'PENANG FERRY'] },
        { name: 'Japan Trip', start: '2026-11-08', end: '2026-11-20', currency: 'Yen', rate: 0.032, match: ['AIRASIA', 'KLOOK', 'JR PASS'] },
      ],
      ownPayees: ['AEON CREDIT SERVICE'],
    },
    passwords: { aeon_credit: 'demo1234' },
    uploaded: new Set(),
  }
}

/** Rows an "upload" adds in the mock, per parser. */
export function demoUploadRows(source: string, label: string): Seed[] {
  const d = '2026-10-14'
  const shared: Record<string, Seed[]> = {
    tng: [
      { date: d, item: 'QR payment', amount: 8.5, remarks: 'To Roti Canai Stall', source: label, needs: ['purpose', 'category'], statement: 'QR Payment ROTI CANAI STALL' },
      { date: d, item: 'Toll', amount: 5.6, category: 'Transport', importance: 'Essential', source: label, statement: 'TOUCH N GO TOLL' },
    ],
    default: [
      { date: d, item: 'Starbucks', amount: 17.9, category: 'Food', importance: 'Nice to Have', source: label, statement: 'STARBUCKS' },
      { date: d, item: 'Transfer', amount: 40, remarks: 'To Mei Ling Wong', source: label, needs: ['purpose', 'category'], statement: 'DuitNow MEI LING WONG', counterparty: 'MEI LING WONG' },
      { date: d, item: 'Guardian', amount: 23.1, category: '', source: label, needs: ['category'], statement: 'GUARDIAN PHARMACY' },
    ],
  }
  return shared[source] ?? shared.default
}

export { toRow }

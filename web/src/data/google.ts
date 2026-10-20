/**
 * The few Google Sheets / Drive REST calls the app makes, with the user's
 * own access token. Scopes: spreadsheets, drive.file (only files this app
 * created) and drive.appdata (its private App Data folder).
 */

const SHEETS = 'https://sheets.googleapis.com/v4/spreadsheets'
const DRIVE = 'https://www.googleapis.com/drive/v3/files'
const UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
const SHEET_MIME = 'application/vnd.google-apps.spreadsheet'
const FOLDER_MIME = 'application/vnd.google-apps.folder'

export type Values = (string | number | boolean)[][]
export interface SheetTab {
  title: string
  sheetId: number
  index: number
  gridProperties?: { columnCount?: number }
}
export type Render = 'FORMULA' | 'UNFORMATTED_VALUE' | 'FORMATTED_VALUE'

export class GoogleError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export class Google {
  private token: () => Promise<string>
  constructor(token: () => Promise<string>) {
    this.token = token
  }

  private async call<T>(url: string, init: RequestInit = {}): Promise<T> {
    let r: Response
    for (let attempt = 0; ; attempt++) {
      r = await fetch(url, {
        ...init,
        headers: { Authorization: `Bearer ${await this.token()}`, ...(init.headers ?? {}) },
      })
      // Sheets allows 60 reads and 60 writes a minute per user; a big import
      // goes over that. Wait for the minute to roll over and try again.
      if (r.status !== 429 || attempt >= 5) break
      const wait = Number(r.headers.get('Retry-After')) || Math.min(5 * 2 ** attempt, 40) + Math.random() * 2
      await new Promise((ok) => setTimeout(ok, wait * 1000))
    }
    if (!r.ok) {
      let msg = `${r.status} ${r.statusText}`
      try {
        msg = (await r.json()).error?.message ?? msg
      } catch {
        /* not JSON */
      }
      throw new GoogleError(r.status, `Google: ${msg}`)
    }
    const text = await r.text()
    return (text ? JSON.parse(text) : {}) as T
  }

  private json(url: string, method: string, body: unknown) {
    return this.call(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  }

  // ---- Drive ----------------------------------------------------------------

  /** Files this app made, by exact name (and optionally type / folder). */
  async findFiles(name: string, mimeType?: string, parent?: string): Promise<{ id: string; name: string }[]> {
    const q = [`name = '${name.replace(/'/g, "\\'")}'`, 'trashed = false']
    if (mimeType) q.push(`mimeType = '${mimeType}'`)
    if (parent) q.push(`'${parent}' in parents`)
    const r = await this.call<{ files: { id: string; name: string }[] }>(
      `${DRIVE}?q=${encodeURIComponent(q.join(' and '))}&fields=files(id,name)&orderBy=createdTime`,
    )
    return r.files ?? []
  }

  /** Spreadsheets this app made whose name contains `text`. */
  async findSpreadsheets(text: string): Promise<{ id: string; name: string }[]> {
    const q = `name contains '${text}' and mimeType = '${SHEET_MIME}' and trashed = false`
    const r = await this.call<{ files: { id: string; name: string }[] }>(
      `${DRIVE}?q=${encodeURIComponent(q)}&fields=files(id,name)`,
    )
    return r.files ?? []
  }

  async folder(name: string, parent?: string): Promise<string> {
    const found = await this.findFiles(name, FOLDER_MIME, parent)
    if (found.length) return found[0].id
    const r = (await this.json(DRIVE, 'POST', {
      name, mimeType: FOLDER_MIME, ...(parent ? { parents: [parent] } : {}),
    })) as { id: string }
    return r.id
  }

  /** Upload a file into a folder (replacing one with the same name). */
  async putFile(folderId: string, name: string, mime: string, data: Uint8Array): Promise<void> {
    const existing = await this.findFiles(name, undefined, folderId)
    if (existing.length) {
      await this.call(`${UPLOAD}/${existing[0].id}?uploadType=media`, {
        method: 'PATCH', headers: { 'Content-Type': mime }, body: data,
      })
      return
    }
    await this.multipart({ name, parents: [folderId] }, mime, data)
  }

  private async multipart(meta: object, mime: string, data: Uint8Array | string): Promise<{ id: string }> {
    const boundary = 'fincomp-' + Math.random().toString(36).slice(2)
    const body = new Blob([
      `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(meta)}\r\n`,
      `--${boundary}\r\nContent-Type: ${mime}\r\n\r\n`,
      data,
      `\r\n--${boundary}--`,
    ])
    return this.call(`${UPLOAD}?uploadType=multipart`, {
      method: 'POST', headers: { 'Content-Type': `multipart/related; boundary=${boundary}` }, body,
    })
  }

  // ---- App Data folder (passwords.json) -------------------------------------------

  async readAppData<T>(name: string, fallback: T): Promise<T> {
    const q = encodeURIComponent(`name = '${name}'`)
    const r = await this.call<{ files: { id: string }[] }>(`${DRIVE}?spaces=appDataFolder&q=${q}&fields=files(id)`)
    if (!r.files?.length) return fallback
    return this.call<T>(`${DRIVE}/${r.files[0].id}?alt=media`)
  }

  async deleteAppData(name: string): Promise<void> {
    const q = encodeURIComponent(`name = '${name}'`)
    const r = await this.call<{ files: { id: string }[] }>(`${DRIVE}?spaces=appDataFolder&q=${q}&fields=files(id)`)
    for (const f of r.files ?? []) await this.call(`${DRIVE}/${f.id}`, { method: 'DELETE' })
  }

  async writeAppData(name: string, value: unknown): Promise<void> {
    const q = encodeURIComponent(`name = '${name}'`)
    const r = await this.call<{ files: { id: string }[] }>(`${DRIVE}?spaces=appDataFolder&q=${q}&fields=files(id)`)
    const body = JSON.stringify(value)
    if (r.files?.length) {
      await this.call(`${UPLOAD}/${r.files[0].id}?uploadType=media`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body,
      })
    } else {
      await this.multipart({ name, parents: ['appDataFolder'] }, 'application/json', body)
    }
  }

  // ---- Sheets ---------------------------------------------------------------------

  async createSpreadsheet(title: string): Promise<string> {
    const r = (await this.json(SHEETS, 'POST', { properties: { title } })) as { spreadsheetId: string }
    return r.spreadsheetId
  }

  async tabs(id: string): Promise<SheetTab[]> {
    const r = await this.call<{ sheets: { properties: SheetTab }[] }>(
      `${SHEETS}/${id}?fields=sheets.properties(title,sheetId,index,gridProperties.columnCount)`,
    )
    return r.sheets.map((s) => s.properties).sort((a, b) => a.index - b.index)
  }

  /** Values for each range, in the same order as `ranges`. */
  async read(id: string, ranges: string[], render: Render): Promise<Values[]> {
    if (!ranges.length) return []
    const qs = ranges.map((r) => `ranges=${encodeURIComponent(r)}`).join('&')
    const r = await this.call<{ valueRanges: { values?: Values }[] }>(
      `${SHEETS}/${id}/values:batchGet?${qs}&valueRenderOption=${render}&dateTimeRenderOption=SERIAL_NUMBER`,
    )
    return r.valueRanges.map((v) => v.values ?? [])
  }

  async write(id: string, data: { range: string; values: unknown[][] }[], input: 'RAW' | 'USER_ENTERED') {
    if (!data.length) return
    await this.json(`${SHEETS}/${id}/values:batchUpdate`, 'POST', { valueInputOption: input, data })
  }

  async clear(id: string, ranges: string[]) {
    if (!ranges.length) return
    await this.json(`${SHEETS}/${id}/values:batchClear`, 'POST', { ranges })
  }

  async append(id: string, range: string, values: unknown[][]) {
    await this.json(
      `${SHEETS}/${id}/values/${encodeURIComponent(range)}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`,
      'POST', { values },
    )
  }

  async batch(id: string, requests: object[]): Promise<{ replies?: Record<string, unknown>[] }> {
    if (!requests.length) return {}
    return this.json(`${SHEETS}/${id}:batchUpdate`, 'POST', { requests }) as Promise<{ replies?: Record<string, unknown>[] }>
  }
}

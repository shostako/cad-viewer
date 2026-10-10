/**
 * 最近開いたファイル (issue #47 item 5): the last RECENT_MAX files opened
 * through the file picker or dropped, kept in this browser only (IndexedDB).
 * What is kept is the file's handle (the File System Access API): Chrome can
 * read the file through it again, after asking once more for leave to read
 * it. The name, size and the time it was opened are kept beside it for the
 * list.
 *
 * A file opened through the plain <input> (a browser without the picker)
 * gives no handle, so it is not listed. The measurements and notes come back
 * from the sidecar, as for any file with the same content.
 */

export const RECENT_MAX = 8

export interface RecentEntry {
  handle: FileSystemFileHandle
  name: string
  size: number
  /** when it was opened last (ms since the epoch) */
  openedAt: number
}

/** the parts of the File System Access API that TypeScript's DOM types leave out */
interface ReadPermission {
  queryPermission?(d: { mode: 'read' }): Promise<PermissionState>
  requestPermission?(d: { mode: 'read' }): Promise<PermissionState>
}
interface PickerOptions {
  id?: string
  startIn?: FileSystemHandle
  multiple?: boolean
  types?: { description: string; accept: Record<string, string[]> }[]
}
type OpenFilePicker = (o?: PickerOptions) => Promise<FileSystemFileHandle[]>

/** the file picker of the File System Access API (Chrome, Edge), or null */
export function filePicker(): OpenFilePicker | null {
  const p = (window as unknown as { showOpenFilePicker?: OpenFilePicker }).showOpenFilePicker
  return typeof p === 'function' ? p.bind(window) : null
}

const DB_NAME = 'cad-viewer'
const STORE = 'recent'
const KEY = 'list'

function request<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result)
    r.onerror = () => reject(r.error)
  })
}

function openDb(): Promise<IDBDatabase> {
  const r = indexedDB.open(DB_NAME, 1)
  r.onupgradeneeded = () => {
    if (!r.result.objectStoreNames.contains(STORE)) r.result.createObjectStore(STORE)
  }
  return request(r)
}

async function readList(): Promise<RecentEntry[]> {
  const db = await openDb()
  try {
    const list = await request(db.transaction(STORE).objectStore(STORE).get(KEY))
    return Array.isArray(list) ? (list as RecentEntry[]).filter((e) => e && e.handle && typeof e.name === 'string') : []
  } finally {
    db.close()
  }
}

async function writeList(list: RecentEntry[]): Promise<void> {
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(list, KEY)
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

/** what a reopen found: the file, or why there is none */
export type Reopened = { file: File } | { problem: 'denied' | 'missing' }

/**
 * The list, newest first, and the changes to it. Every change is written to
 * IndexedDB at once (the next visit sees it); `onChange` redraws the lists on
 * screen. Storage that does not work (a private window, blocked site data)
 * leaves an empty list that lives only as long as the page.
 */
export class RecentFiles {
  entries: RecentEntry[] = []
  private readonly onChange: (entries: readonly RecentEntry[]) => void
  /** the changes in the order they were asked for (each reads what the one before wrote) */
  private queue: Promise<unknown> = Promise.resolve()

  constructor(onChange: (entries: readonly RecentEntry[]) => void) {
    this.onChange = onChange
  }

  /** read the list kept in this browser */
  load(): Promise<void> {
    return this.change(async () => {
      try {
        this.entries = await readList()
      } catch {
        this.entries = []
      }
    })
  }

  /** a file opened through its handle goes to the top (the same file moves up; the oldest beyond RECENT_MAX goes) */
  remember(handle: FileSystemFileHandle, file: File): Promise<void> {
    return this.change(async () => {
      const kept: RecentEntry[] = []
      for (const e of this.entries) if (!(await sameEntry(e.handle, handle))) kept.push(e)
      this.entries = [{ handle, name: file.name, size: file.size, openedAt: Date.now() }, ...kept].slice(0, RECENT_MAX)
      await this.save()
    })
  }

  /** take an entry off the list */
  forget(entry: RecentEntry): Promise<void> {
    return this.change(async () => {
      this.entries = this.entries.filter((e) => e !== entry)
      await this.save()
    })
  }

  private change(f: () => Promise<void>): Promise<void> {
    const next = this.queue.then(f).finally(() => this.onChange(this.entries))
    this.queue = next.catch(() => undefined)
    return next
  }

  private async save(): Promise<void> {
    try {
      await writeList(this.entries)
    } catch {
      /* not kept for the next visit; the list on screen is still right */
    }
  }
}

async function sameEntry(a: FileSystemFileHandle, b: FileSystemFileHandle): Promise<boolean> {
  try {
    return await a.isSameEntry(b)
  } catch {
    return false
  }
}

/**
 * Read a listed file again. Chrome asks for leave to read it once more (the
 * click on the row is the gesture that may ask); the file may also have been
 * moved or deleted since.
 */
export async function reopen(entry: RecentEntry): Promise<Reopened> {
  const h = entry.handle as FileSystemFileHandle & ReadPermission
  let leave: PermissionState = 'granted'
  if (h.queryPermission) leave = await h.queryPermission({ mode: 'read' })
  if (leave !== 'granted' && h.requestPermission) leave = await h.requestPermission({ mode: 'read' })
  if (leave !== 'granted') return { problem: 'denied' }
  try {
    return { file: await h.getFile() }
  } catch (e) {
    if (e instanceof DOMException && (e.name === 'NotFoundError' || e.name === 'NotReadableError')) return { problem: 'missing' }
    throw e
  }
}

/** 「10/10 18:40」 (this year), 「2025/10/10」 (another year) */
export function whenText(ms: number, now = Date.now()): string {
  const d = new Date(ms)
  const two = (v: number) => String(v).padStart(2, '0')
  if (d.getFullYear() !== new Date(now).getFullYear()) return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
  return `${d.getMonth() + 1}/${d.getDate()} ${two(d.getHours())}:${two(d.getMinutes())}`
}

/** 「39 KB」「1.2 MB」 */
export function sizeText(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * The rows of a list of recent files: a button that opens the file (its name,
 * when it was opened, its size) and a × that takes it off the list.
 */
export function renderRecentRows(
  el: HTMLElement,
  entries: readonly RecentEntry[],
  open: (e: RecentEntry) => void,
  forget: (e: RecentEntry) => void,
): void {
  const rows = entries.map((entry) => {
    const row = document.createElement('div')
    row.className = 'recent-row'
    const openBtn = document.createElement('button')
    openBtn.type = 'button'
    openBtn.className = 'recent-open'
    openBtn.title = `${entry.name} を開く`
    const name = document.createElement('span')
    name.className = 'recent-name'
    name.textContent = entry.name
    const meta = document.createElement('span')
    meta.className = 'recent-meta'
    meta.textContent = `${whenText(entry.openedAt)} ・ ${sizeText(entry.size)}`
    openBtn.append(name, meta)
    openBtn.addEventListener('click', () => open(entry))
    const x = document.createElement('button')
    x.type = 'button'
    x.className = 'recent-forget'
    x.setAttribute('aria-label', `${entry.name} を一覧から消す`)
    x.title = '一覧から消す（ファイルはそのまま）'
    x.textContent = '×'
    x.addEventListener('click', (ev) => {
      ev.stopPropagation()
      forget(entry)
    })
    row.append(openBtn, x)
    return row
  })
  el.replaceChildren(...rows)
}

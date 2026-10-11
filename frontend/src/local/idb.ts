/**
 * the sidecars in the browser's IndexedDB (database cad-viewer-sidecars, store
 * sidecars, by content hash). Not the database cad-viewer: recent.ts's, whose
 * version is its own.
 */
import type { SidecarStore } from './backend.ts'

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('cad-viewer-sidecars', 1)
    req.onupgradeneeded = () => req.result.createObjectStore('sidecars')
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export function idbStore(): SidecarStore {
  let db: Promise<IDBDatabase> | null = null
  const store = async (mode: IDBTransactionMode) => (await (db ??= open())).transaction('sidecars', mode).objectStore('sidecars')
  const done = <T>(req: IDBRequest<T>) =>
    new Promise<T>((resolve, reject) => {
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    })
  return {
    get: async (hash) => done((await store('readonly')).get(hash)),
    put: async (hash, value) => void (await done((await store('readwrite')).put(value, hash))),
  }
}

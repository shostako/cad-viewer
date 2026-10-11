/**
 * Where the app's calculations are done (docs/designs/web-version.md): the
 * backend over HTTP (a checkout, the installed app), or, in the Web version, a
 * Worker in this page (local/). api.ts is the only caller.
 *
 * The Engine answers the backend's own requests (the same paths, methods,
 * statuses and bodies, as a Response), so api.ts reads every answer, and every
 * error, the one way, whichever does the work; an E2E that holds or answers a
 * request by its path works on both.
 */

/** an upload's answer: the status and the body as the backend sends them */
export interface UploadAnswer {
  status: number
  statusText: string
  body: string
}

export interface Engine {
  /** a request to the backend's /api (path from /api/...) */
  fetch(path: string, init?: RequestInit): Promise<Response>
  /**
   * POST /api/models with the file. onSent: how much of the file has gone (0..1;
   * 1 once all of it has, when the conversion starts). Rejects with status 0
   * when no answer came (the network, an abort).
   */
  upload(file: File, onSent?: (fraction: number) => void): Promise<UploadAnswer>
}

/** the backend at this page's origin (/api; Vite's dev server passes it on) */
export const httpEngine: Engine = {
  fetch: (path, init) => fetch(path, init),
  upload(file, onSent) {
    // XMLHttpRequest, not fetch: only it tells how much of the file has gone up
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/models')
      if (onSent) {
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable && e.total > 0) onSent(e.loaded / e.total)
        })
        xhr.upload.addEventListener('load', () => onSent(1))
      }
      xhr.addEventListener('load', () => resolve({ status: xhr.status, statusText: xhr.statusText, body: xhr.responseText }))
      xhr.addEventListener('error', () => reject(new EngineUnreachable('no answer from the backend (network error)')))
      xhr.addEventListener('abort', () => reject(new EngineUnreachable('the upload was aborted')))
      const form = new FormData()
      form.append('file', file)
      xhr.send(form)
    })
  },
}

/** no answer at all (the backend is not there, the request was cut) */
export class EngineUnreachable extends Error {}

/** the Web version's (local/client.ts), loaded on its first use; not in the checkout's build at all */
function lazyLocal(): Engine {
  const load = () => import('./local/client.ts').then((m) => m.localEngine)
  return {
    fetch: async (path, init) => (await load()).fetch(path, init),
    upload: async (file, onSent) => (await load()).upload(file, onSent),
  }
}

/** the engine this build uses: VITE_CAD_ENGINE=local (npm run build:web) is the Web version's */
export const isLocal = import.meta.env.VITE_CAD_ENGINE === 'local'
export const engine: Engine = isLocal ? lazyLocal() : httpEngine

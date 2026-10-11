/**
 * The Web version as an app of its own (docs/designs/web-version.md, W7):
 *
 * - offline: the service worker (sw.js, made by the build: vite.config.ts)
 *   keeps the page and the parts it has used, and answers with them when the
 *   network is not there. Only in the Web version's build (not the checkout's,
 *   not Vite's dev server).
 * - files opened with it: installed (Chrome, Edge), the app is offered for
 *   STEP, IGES, STL… files on the PC (manifest.webmanifest's file_handlers).
 *   Such a file arrives through window.launchQueue as a file handle, and is
 *   opened as one chosen in the file picker (so it goes on the recent list).
 */
import { isLocal } from './engine'

interface LaunchParams {
  files?: readonly FileSystemHandle[]
}
interface LaunchQueue {
  setConsumer(consumer: (params: LaunchParams) => void): void
}

/** open: what opens a file chosen in the picker (main.ts) */
export function startWebApp(open: (handle: FileSystemFileHandle) => void): void {
  const launchQueue = (window as unknown as { launchQueue?: LaunchQueue }).launchQueue
  launchQueue?.setConsumer((params) => {
    const handle = params.files?.find((h) => h.kind === 'file')
    if (handle) open(handle as FileSystemFileHandle)
  })
  if (isLocal && import.meta.env.PROD && 'serviceWorker' in navigator) {
    // next to the page (GitHub Pages serves the app from /cad-viewer/)
    navigator.serviceWorker.register('./sw.js').catch(() => undefined) // no offline then; the page works as before
  }
}

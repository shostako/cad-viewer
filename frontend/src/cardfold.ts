/**
 * Folding a card of the bottom-right stack (問題の一覧, 計測) to its head: its
 * title is a button with a chevron (as the operation panel's folders), and
 * what the card keeps folded is the caller's (the counts, the copy button).
 * Whether a card is folded survives a reload.
 */
import { ICON, icon } from './icons'

export function loadFolded(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false // storage unavailable (private window, blocked site data)
  }
}

function saveFolded(key: string, on: boolean): void {
  try {
    localStorage.setItem(key, on ? '1' : '0')
  } catch {
    /* best-effort */
  }
}

/**
 * The title as the fold's button: 「⌄ 問題の一覧」 open, 「› 問題の一覧」 folded.
 * card: the card (it gets the class "folded"); title: the heading's own element
 * (its look stays the panels' heading's). The column lays itself out again
 * from the card's new size (main.ts observes both cards).
 */
export function foldButton(card: HTMLElement, title: HTMLElement, key: string): HTMLButtonElement {
  const b = document.createElement('button')
  b.type = 'button'
  b.className = 'card-fold'
  b.append(icon(ICON.recent, 13), title)
  const show = () => {
    const folded = card.classList.contains('folded')
    b.setAttribute('aria-expanded', String(!folded))
    b.title = folded ? 'ひらく' : 'たたむ（見出しの行だけにする）'
  }
  card.classList.toggle('folded', loadFolded(key))
  show()
  b.addEventListener('click', () => {
    const on = !card.classList.contains('folded')
    card.classList.toggle('folded', on)
    saveFolded(key, on)
    show()
  })
  return b
}

/**
 * The OCCT objects one calculation makes, deleted together at its end.
 *
 * Embind frees an object only on .delete(): its finalizer covers the smart
 * pointers (OCCT's Handle<>) only, and libcascade hands back a copy of its own
 * for each call that returns an object (map.FindKey(i) twice is two objects).
 * A temporary left alive stays in the Worker's WebAssembly memory for good, so
 * every object a calculation constructs or is handed back goes in its bag:
 *
 *     withBag((k) => {
 *       const surf = k(new oc.BRepAdaptor_Surface(face, true))
 *       return xyz(k(k(surf.Plane()).Axis()).Direction())   // numbers out
 *     })
 *
 * What the model keeps (its shapes and maps) does not go in a bag.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

/** puts an object in the bag and gives it back (a plain value, as it is) */
export type Keep = <T>(o: T) => T

export class Bag {
  private readonly all = new Set<any>()

  readonly k: Keep = (o) => {
    if (o !== null && typeof o === 'object' && typeof (o as any).delete === 'function') this.all.add(o)
    return o
  }

  /** deletes them all, the last made first */
  free(): void {
    const all = [...this.all].reverse()
    this.all.clear()
    for (const o of all) if (!o.isDeleted?.()) o.delete()
  }
}

/** f with a bag of its own, emptied when f returns or throws */
export function withBag<T>(f: (k: Keep) => T): T {
  const bag = new Bag()
  try {
    return f(bag.k)
  } finally {
    bag.free()
  }
}

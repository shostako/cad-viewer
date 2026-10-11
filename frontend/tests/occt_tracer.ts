/**
 * For the leak checks of the Web version's OpenCASCADE code (local_measure,
 * local_brep): embind frees an object only on .delete() (src/local/occtbag.ts).
 */
/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * the OCCT objects a calculation gets hold of, for the leak check: oc wrapped,
 * every object that comes out of a constructor or a call recorded (what the
 * model keeps is wrapped by own(), and not recorded). The calculation sees
 * wrappers; OCCT sees the objects themselves.
 */
export function tracer(oc: any) {
  const made: any[] = []
  const raw = new WeakMap<object, any>()
  const unwrap = (v: any) => (v !== null && typeof v === 'object' && raw.has(v) ? raw.get(v) : v)
  const wrapObject = (t: any, record: boolean): any => {
    if (record) made.push(t)
    const px = new Proxy(t, {
      get(target, prop) {
        const v = target[prop]
        if (typeof v !== 'function') return v
        if (prop === 'delete' || prop === 'isDeleted') return v.bind(target)
        return (...args: any[]) => out(v.apply(target, args.map(unwrap)))
      },
    })
    raw.set(px, t)
    return px
  }
  const out = (v: any) => (v !== null && typeof v === 'object' && typeof v.delete === 'function' ? wrapObject(v, true) : v)
  const wrapFunction = (f: any): any =>
    new Proxy(f, {
      construct: (target, args) => out(new target(...args.map(unwrap))),
      apply: (target, self, args) => out(target.apply(self, args.map(unwrap))),
      get: (target, prop) => (typeof target[prop] === 'function' ? wrapFunction(target[prop]) : target[prop]),
    })
  const wrapped = new Proxy(oc, { get: (target, prop) => (typeof target[prop] === 'function' ? wrapFunction(target[prop]) : target[prop]) })
  /** raw(wrapper): the object itself */
  return { oc: wrapped, own: (t: any) => wrapObject(t, false), raw: (p: any) => raw.get(p) ?? p, made }
}

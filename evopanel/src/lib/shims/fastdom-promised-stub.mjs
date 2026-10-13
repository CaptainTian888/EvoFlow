/**
 * fastdom-promised stub for Vite ESM interop.
 * 
 * Extension of fastdom for promise-based API; same approach as fastdom-stub.
 */

export default {}
export const fastdom = {}
export const read = () => Promise.resolve()
export const write = (fn) => Promise.resolve(fn?.())
export const measure = () => Promise.resolve()
export const mutate = (fn) => Promise.resolve(fn?.())

/**
 * fastdom stub for Vite ESM interop.
 * 
 * fastdom is UMD-only and breaks Vite's ESM handling when imported by mermaid.
 * Mermaid has a try/catch fallback for missing fastdom, so we provide an empty stub
 * to satisfy the import and let mermaid continue without fastdom optimization.
 */

export default {}
export const fastdom = {}
export const read = () => {}
export const write = (fn) => fn?.()
export const measure = () => {}
export const mutate = (fn) => fn?.()

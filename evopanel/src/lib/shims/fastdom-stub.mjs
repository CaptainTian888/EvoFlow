/**
 * Minimal fastdom API for Mermaid's ESM imports.
 * Mermaid extends the default export and uses measure() to read layout.
 */
function extend(extension = {}) {
  return Object.assign(Object.create(fastdom), extension)
}

const fastdom = {
  extend,
  read(fn) {
    return fn?.()
  },
  write(fn) {
    return fn?.()
  },
  measure(fn) {
    return fn?.()
  },
  mutate(fn) {
    return fn?.()
  },
}

export default fastdom
export { fastdom }
export const read = fastdom.read
export const write = fastdom.write
export const measure = fastdom.measure
export const mutate = fastdom.mutate

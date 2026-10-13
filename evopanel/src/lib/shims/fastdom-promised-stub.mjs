/**
 * Promise-based fastdom extension used by Mermaid.
 */
const fastdomPromised = {
  extend(extension = {}) {
    return Object.assign(Object.create(this), extension)
  },
  read(fn) {
    return Promise.resolve().then(() => fn?.())
  },
  write(fn) {
    return Promise.resolve().then(() => fn?.())
  },
  measure(fn) {
    return Promise.resolve().then(() => fn?.())
  },
  mutate(fn) {
    return Promise.resolve().then(() => fn?.())
  },
}

export default fastdomPromised
export { fastdomPromised as fastdom }
export const read = fastdomPromised.read
export const write = fastdomPromised.write
export const measure = fastdomPromised.measure
export const mutate = fastdomPromised.mutate

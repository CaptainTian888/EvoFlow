/**
 * Asset Center file-content warm cache (same idea as session-list history prefetch).
 * Enter page → warm first visible docs; hover row → warm that path; click → paint from cache.
 */
import { api } from './tauri-api.js'

const TTL_MS = 60_000
const MAX_ENTRIES = 48

/** @type {Map<string, { at: number, content: string }>} */
const _cache = new Map()
/** @type {Map<string, Promise<string | null>>} */
const _inflight = new Map()

/**
 * @param {{ entityType?: string, entityId?: string }} entity
 * @param {string} path
 */
export function assetFileCacheKey(entity, path) {
  const et = String(entity?.entityType || '').trim()
  const eid = String(entity?.entityId || '').trim()
  const p = String(path || '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
  return `${et}|${eid}|${p}`
}

function prune(now = Date.now()) {
  for (const [k, hit] of _cache) {
    if (now - hit.at >= TTL_MS) _cache.delete(k)
  }
  if (_cache.size <= MAX_ENTRIES) return
  const ordered = [..._cache.entries()].sort((a, b) => a[1].at - b[1].at)
  const drop = _cache.size - MAX_ENTRIES
  for (let i = 0; i < drop; i++) _cache.delete(ordered[i][0])
}

/**
 * @param {{ entityType?: string, entityId?: string }} entity
 * @param {string} path
 * @returns {string | null}
 */
export function peekAssetFileCache(entity, path) {
  const key = assetFileCacheKey(entity, path)
  if (!key.endsWith('|') && !path) return null
  const hit = _cache.get(key)
  if (!hit) return null
  if (Date.now() - hit.at > TTL_MS) {
    _cache.delete(key)
    return null
  }
  return hit.content
}

/**
 * @param {{ entityType?: string, entityId?: string }} entity
 * @param {string} path
 * @param {string} content
 */
export function putAssetFileCache(entity, path, content) {
  const key = assetFileCacheKey(entity, path)
  if (!String(path || '').trim()) return
  prune()
  _cache.set(key, { at: Date.now(), content: String(content ?? '') })
}

/**
 * @param {{ entityType?: string, entityId?: string }} entity
 * @param {string} [pathPrefix] if set, only clear keys under this entity (+ optional path prefix)
 */
export function clearAssetFileCache(entity, pathPrefix = '') {
  const et = String(entity?.entityType || '').trim()
  const eid = String(entity?.entityId || '').trim()
  const prefix = `${et}|${eid}|`
  const pathP = String(pathPrefix || '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
  for (const k of [..._cache.keys()]) {
    if (!k.startsWith(prefix)) continue
    if (pathP && !k.slice(prefix.length).startsWith(pathP)) continue
    _cache.delete(k)
  }
  for (const k of [..._inflight.keys()]) {
    if (!k.startsWith(prefix)) continue
    if (pathP && !k.slice(prefix.length).startsWith(pathP)) continue
    _inflight.delete(k)
  }
}

/**
 * Background warm one file. Dedupes in-flight + fresh cache hits.
 * @param {{ entityType?: string, entityId?: string }} entity
 * @param {string} path
 * @param {{ force?: boolean }} [opts] force=true bypasses cache and refetches
 * @returns {Promise<string | null>}
 */
export function warmAssetFile(entity, path, opts = {}) {
  const p = String(path || '')
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
  if (!p) return Promise.resolve(null)
  prune()
  const key = assetFileCacheKey(entity, p)
  const force = Boolean(opts?.force)
  if (!force) {
    const hit = peekAssetFileCache(entity, p)
    if (hit != null) return Promise.resolve(hit)
  }
  const pending = _inflight.get(key)
  if (pending) return pending

  const job = (async () => {
    try {
      const data = await api.assetsReadFile({ ...entity, path: p })
      const content = String(data?.content ?? '')
      putAssetFileCache(entity, p, content)
      return content
    } catch {
      return null
    } finally {
      _inflight.delete(key)
    }
  })()
  _inflight.set(key, job)
  return job
}

/**
 * Warm the first N file paths (serial-ish with small concurrency to avoid hammering gateway).
 * @param {{ entityType?: string, entityId?: string }} entity
 * @param {string[]} paths
 * @param {{ limit?: number, concurrency?: number }} [opts]
 */
export async function warmAssetFileBatch(entity, paths, opts = {}) {
  const limit = Math.max(1, Number(opts.limit) || 8)
  const concurrency = Math.max(1, Math.min(3, Number(opts.concurrency) || 2))
  const list = (Array.isArray(paths) ? paths : [])
    .map((p) =>
      String(p || '')
        .replace(/\\/g, '/')
        .replace(/^\/+/, ''),
    )
    .filter(Boolean)
    .filter((p, i, arr) => arr.indexOf(p) === i)
    .slice(0, limit)

  let i = 0
  const workers = Array.from({ length: Math.min(concurrency, list.length) }, async () => {
    while (i < list.length) {
      const path = list[i++]
      await warmAssetFile(entity, path)
    }
  })
  await Promise.all(workers)
}

import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../src/lib/tauri-api.js', () => ({
  api: {
    assetsReadFile: vi.fn(async ({ path }) => ({ content: `body:${path}` })),
  },
}))

import { api } from '../src/lib/tauri-api.js'
import {
  clearAssetFileCache,
  peekAssetFileCache,
  putAssetFileCache,
  warmAssetFile,
  warmAssetFileBatch,
} from '../src/lib/assets-file-prefetch.js'

const entity = { entityType: 'user', entityId: 'user' }

describe('assets-file-prefetch', () => {
  beforeEach(() => {
    clearAssetFileCache(entity)
    api.assetsReadFile.mockClear()
  })

  it('put / peek round-trip', () => {
    putAssetFileCache(entity, 'craft/a.md', 'hello')
    expect(peekAssetFileCache(entity, 'craft/a.md')).toBe('hello')
  })

  it('warmAssetFile caches and dedupes in-flight', async () => {
    const a = warmAssetFile(entity, 'craft/x.md')
    const b = warmAssetFile(entity, 'craft/x.md')
    const [ca, cb] = await Promise.all([a, b])
    expect(ca).toBe('body:craft/x.md')
    expect(cb).toBe('body:craft/x.md')
    expect(api.assetsReadFile).toHaveBeenCalledTimes(1)
    expect(peekAssetFileCache(entity, 'craft/x.md')).toBe('body:craft/x.md')
  })

  it('warmAssetFileBatch warms first N paths', async () => {
    await warmAssetFileBatch(
      entity,
      ['craft/1.md', 'craft/2.md', 'craft/3.md', 'craft/4.md'],
      { limit: 2, concurrency: 2 },
    )
    expect(peekAssetFileCache(entity, 'craft/1.md')).toBeTruthy()
    expect(peekAssetFileCache(entity, 'craft/2.md')).toBeTruthy()
    expect(peekAssetFileCache(entity, 'craft/3.md')).toBeNull()
  })

  it('warmAssetFile force bypasses cache and refetches', async () => {
    putAssetFileCache(entity, 'craft/y.md', 'stale')
    api.assetsReadFile.mockResolvedValueOnce({ content: 'fresh' })
    const out = await warmAssetFile(entity, 'craft/y.md', { force: true })
    expect(out).toBe('fresh')
    expect(api.assetsReadFile).toHaveBeenCalledTimes(1)
    expect(peekAssetFileCache(entity, 'craft/y.md')).toBe('fresh')
  })
})

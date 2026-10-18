import { describe, expect, it, beforeEach, vi } from 'vitest'

// idle-nav-warm：boot 后空闲预热高频菜单模块，只 warm 模块不预取数据。
// prefetchRoute 依赖 hash 路由表（registerRoute），测试里注册假 loader 验证调用面。

vi.mock('../src/router.js', () => ({
  prefetchRoute: vi.fn(() => Promise.resolve({ render: () => '' })),
}))

import { prefetchRoute } from '../src/router.js'
import { warmFrequentMenuModules } from '../src/boot/idle-nav-warm.js'

describe('idle-nav-warm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('warms each frequent menu route exactly once', async () => {
    // jsdom/happy-dom 无 requestIdleCallback 时模块内建 setTimeout 回退
    warmFrequentMenuModules()
    await new Promise((r) => setTimeout(r, 1500))
    expect(prefetchRoute).toHaveBeenCalledTimes(6)
    const warmed = prefetchRoute.mock.calls.map((c) => c[0])
    for (const p of ['/tasks', '/apps', '/proactive', '/knowledge', '/assets', '/cron']) {
      expect(warmed).toContain(p)
    }
  })

  it('is idempotent — second call warms nothing again', async () => {
    warmFrequentMenuModules()
    warmFrequentMenuModules()
    await new Promise((r) => setTimeout(r, 100))
    expect(prefetchRoute).not.toHaveBeenCalled()
  })

  it('prefetchRoute rejection does not break the warm loop', async () => {
    prefetchRoute.mockImplementation(() => Promise.reject(new Error('cold')))
    // 模块级 _warmed 已置位；重新 import 一份新实例验证吞错路径
    vi.resetModules()
    const { warmFrequentMenuModules: warmAgain } = await import('../src/boot/idle-nav-warm.js')
    expect(() => warmAgain()).not.toThrow()
    await new Promise((r) => setTimeout(r, 1500))
  })
})

/**
 * 流式渲染性能追踪：在每条 delta 的关键环节埋点，卡顿时打日志定位瓶颈。
 *
 * 开关：?streamperf=1 或 localStorage.evoflow_streamperf=1
 *   开启后：单环节 > PHASE_WARN_MS 或 delta 总 > DELTA_WARN_MS 时 console.warn
 *   聚合：window.__streamPerf.report() 打各环节 p50/p95/max
 *
 * 关闭时所有函数空操作，零开销。
 */

const PHASE_WARN_MS = 4
const DELTA_WARN_MS = 12
const WINDOW_SIZE = 200

function now(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

function detectEnabled(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const stored = localStorage.getItem('evoflow_streamperf')
    if (stored === '1') return true
    if (stored === '0') return false
  } catch {
    /* ignore */
  }
  try {
    if (new URLSearchParams(window.location.search).get('streamperf') === '1') return true
  } catch {
    /* ignore */
  }
  return false
}

let enabled = detectEnabled()

type PhaseStats = {
  samples: number[] // 滑动窗口（最近 WINDOW_SIZE 条 delta 的该 phase 耗时）
  max: number
}

const phaseStats = new Map<string, PhaseStats>()
let currentDeltaPhases: Map<string, number> | null = null
let currentDeltaStart = 0
let currentDeltaSeq = -1

function ensureStats(phase: string): PhaseStats {
  let s = phaseStats.get(phase)
  if (!s) {
    s = { samples: [], max: 0 }
    phaseStats.set(phase, s)
  }
  return s
}

function percentile(sorted: number[], p: number): number {
  if (!sorted.length) return 0
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)
  return sorted[Math.max(0, idx)]
}

/** 每条流式 delta 开始时调用（在 MessageVirtualList render 开头）。 */
export function streamPerfBeginDelta(seq: number): void {
  if (!enabled) return
  currentDeltaPhases = new Map()
  currentDeltaStart = now()
  currentDeltaSeq = seq
}

/** 计时包裹一个同步环节。关闭时直接执行 fn，零开销。 */
export function streamPerfTime<T>(phase: string, fn: () => T): T {
  if (!enabled) return fn()
  const t0 = now()
  const result = fn()
  const ms = now() - t0
  if (currentDeltaPhases) {
    currentDeltaPhases.set(phase, (currentDeltaPhases.get(phase) || 0) + ms)
  }
  if (ms > PHASE_WARN_MS) {
    console.warn(`[streamperf] phase "${phase}" 慢: ${ms.toFixed(1)}ms`)
  }
  return result
}

/** 每条流式 delta 结束时调用（在 MessageVirtualList useEffect/layoutEffect）。 */
export function streamPerfEndDelta(): void {
  if (!enabled || !currentDeltaPhases) return
  const total = now() - currentDeltaStart
  // 计入各 phase 滑动窗口
  for (const [phase, ms] of currentDeltaPhases) {
    const s = ensureStats(phase)
    s.samples.push(ms)
    if (s.samples.length > WINDOW_SIZE) s.samples.shift()
    if (ms > s.max) s.max = ms
  }
  // delta 总耗时超阈值：打详细分解
  if (total > DELTA_WARN_MS) {
    const breakdown: Record<string, number> = {}
    for (const [phase, ms] of currentDeltaPhases) breakdown[phase] = +ms.toFixed(1)
    console.warn(
      `[streamperf] delta #${currentDeltaSeq} 总耗时 ${total.toFixed(1)}ms（超 ${DELTA_WARN_MS}ms 阈值）`,
      breakdown,
    )
  }
  currentDeltaPhases = null
}

/** 聚合报告：各环节 p50/p95/max（ms）。 */
export function streamPerfReport(): Record<string, { p50: number; p95: number; max: number; count: number }> {
  const out: Record<string, { p50: number; p95: number; max: number; count: number }> = {}
  for (const [phase, s] of phaseStats) {
    const sorted = [...s.samples].sort((a, b) => a - b)
    out[phase] = {
      p50: +percentile(sorted, 50).toFixed(1),
      p95: +percentile(sorted, 95).toFixed(1),
      max: +s.max.toFixed(1),
      count: s.samples.length,
    }
  }
  return out
}

export function streamPerfEnabled(): boolean {
  return enabled
}

export function streamPerfReset(): void {
  phaseStats.clear()
}

/** 安装 window.__streamPerf 调试入口。 */
export function installStreamPerfGlobal(): void {
  if (typeof window === 'undefined') return
  const g = window as unknown as Record<string, unknown>
  g.__streamPerf = {
    report: () => {
      const r = streamPerfReport()
      console.table(r)
      return r
    },
    reset: streamPerfReset,
    enabled: () => enabled,
  }
}
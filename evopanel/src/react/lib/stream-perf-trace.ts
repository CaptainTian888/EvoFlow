/**
 * 流式渲染性能追踪：多维指标交叉定位卡顿根因。
 *
 * 指标维度：
 *   1. 耗时分解（各 phase ms）→ 哪个环节慢
 *   2. 重渲染行数 / 可见行数 → memo 是否生效
 *   3. delta 频率（次/秒）→ 是否渲染风暴
 *   4. 轮次恶化（当前 / 基线）→ 是否累积型
 *   5. 内存趋势 → GC 压力
 *
 * 开关：?streamperf=1 或 localStorage.evoflow_streamperf=1
 *   开启后：单环节 > PHASE_WARN_MS 或 delta 总 > DELTA_WARN_MS 时 console.warn
 *   聚合：window.__streamPerf.report() 打各环节 p50/p95/max + 多维诊断
 *
 * 关闭时所有函数空操作，零开销。
 */

const PHASE_WARN_MS = 4
const DELTA_WARN_MS = 12
const WINDOW_SIZE = 200
const MEM_SAMPLE_INTERVAL = 50

function now(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now()
}

function detectEnabled(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const stored = localStorage.getItem('evoflow_streamperf')
    if (stored === '0') return false
    if (stored === '1') return true
  } catch {
    /* ignore */
  }
  try {
    if (new URLSearchParams(window.location.search).get('streamperf') === '0') return false
  } catch {
    /* ignore */
  }
  return true
}

let enabled = detectEnabled()

type PhaseStats = {
  samples: number[]
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

let lastDeltaSeq = -1
let renderCountThisDelta = 0
let visibleRowCountThisDelta = 0
let deltaTimestamps: number[] = []
let baselineDeltaTotal = 0
let baselineDeltaSeq = -1
let memSamples: { seq: number; mb: number }[] = []
let memSampleCounter = 0

const renderCountStats = { samples: [] as number[], max: 0 }
const memoHitRateStats = { samples: [] as number[], max: 0 }

export function streamPerfBeginDelta(seq: number): void {
  if (!enabled) return
  if (seq === lastDeltaSeq) {
    currentDeltaPhases = null
    return
  }
  lastDeltaSeq = seq
  currentDeltaPhases = new Map()
  currentDeltaStart = now()
  currentDeltaSeq = seq
  renderCountThisDelta = 0
  visibleRowCountThisDelta = 0
}

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

export function streamPerfCountRender(): void {
  if (!enabled || !currentDeltaPhases) return
  renderCountThisDelta++
}

export function streamPerfSetVisibleRows(n: number): void {
  if (!enabled || !currentDeltaPhases) return
  visibleRowCountThisDelta = n
}

export function streamPerfEndDelta(): void {
  if (!enabled || !currentDeltaPhases) return
  const total = now() - currentDeltaStart

  for (const [phase, ms] of currentDeltaPhases) {
    const s = ensureStats(phase)
    s.samples.push(ms)
    if (s.samples.length > WINDOW_SIZE) s.samples.shift()
    if (ms > s.max) s.max = ms
  }

  renderCountStats.samples.push(renderCountThisDelta)
  if (renderCountStats.samples.length > WINDOW_SIZE) renderCountStats.samples.shift()
  if (renderCountThisDelta > renderCountStats.max) renderCountStats.max = renderCountThisDelta

  const memoHitRate =
    visibleRowCountThisDelta > 0
      ? 1 - renderCountThisDelta / visibleRowCountThisDelta
      : 1
  memoHitRateStats.samples.push(memoHitRate)
  if (memoHitRateStats.samples.length > WINDOW_SIZE) memoHitRateStats.samples.shift()

  deltaTimestamps.push(now())
  if (deltaTimestamps.length > WINDOW_SIZE) deltaTimestamps.shift()

  if (baselineDeltaTotal === 0 && total > 0 && total < DELTA_WARN_MS) {
    baselineDeltaTotal = total
    baselineDeltaSeq = currentDeltaSeq
  }

  memSampleCounter++
  if (memSampleCounter >= MEM_SAMPLE_INTERVAL) {
    memSampleCounter = 0
    const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory
    if (mem) {
      memSamples.push({ seq: currentDeltaSeq, mb: mem.usedJSHeapSize / 1048576 })
      if (memSamples.length > WINDOW_SIZE) memSamples.shift()
    }
  }

  const degradation = baselineDeltaTotal > 0 ? total / baselineDeltaTotal : 1

  if (total > DELTA_WARN_MS) {
    const breakdown: Record<string, number> = {}
    for (const [phase, ms] of currentDeltaPhases) breakdown[phase] = +ms.toFixed(1)
    console.warn(
      `[streamperf] delta #${currentDeltaSeq} ${total.toFixed(1)}ms` +
        ` | render=${renderCountThisDelta}/${visibleRowCountThisDelta}行` +
        ` | memo命中=${(memoHitRate * 100).toFixed(0)}%` +
        ` | 恶化=${degradation.toFixed(1)}x`,
      breakdown,
    )
  }

  if (
    visibleRowCountThisDelta > 0 &&
    renderCountThisDelta > visibleRowCountThisDelta * 0.8 &&
    renderCountThisDelta >= 5
  ) {
    console.warn(
      `[streamperf] memo 大面积失效: ${renderCountThisDelta}/${visibleRowCountThisDelta} 行重渲染` +
        `（命中率 ${(memoHitRate * 100).toFixed(0)}%）`,
    )
  }

  if (degradation > 3 && total > DELTA_WARN_MS) {
    console.warn(
      `[streamperf] 累积恶化: 当前 ${total.toFixed(1)}ms vs 基线 ${baselineDeltaTotal.toFixed(1)}ms` +
        `（${degradation.toFixed(1)}x，基线 delta #${baselineDeltaSeq}）`,
    )
  }

  lastDeltaSnapshot = {
    seq: currentDeltaSeq,
    total: +total.toFixed(1),
    renderRows: renderCountThisDelta,
    visibleRows: visibleRowCountThisDelta,
    memoHitRate: +memoHitRate.toFixed(2),
    degradation: +degradation.toFixed(1),
    phases: Object.fromEntries(currentDeltaPhases),
  }
  currentDeltaPhases = null
}

let lastDeltaSnapshot: {
  seq: number
  total: number
  renderRows: number
  visibleRows: number
  memoHitRate: number
  degradation: number
  phases: Record<string, number>
} | null = null

let longTaskObserver: PerformanceObserver | null = null
function installLongTaskMonitor(): void {
  if (longTaskObserver || typeof PerformanceObserver === 'undefined') return
  try {
    longTaskObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const dur = entry.duration
        const snap = lastDeltaSnapshot
        if (snap) {
          console.warn(
            `[streamperf] long task ${dur.toFixed(0)}ms — delta #${snap.seq} ${snap.total}ms` +
              ` | render=${snap.renderRows}/${snap.visibleRows}行 | 恶化=${snap.degradation}x`,
            snap.phases,
          )
        } else {
          console.warn(`[streamperf] long task ${dur.toFixed(0)}ms（无 delta 上下文）`)
        }
      }
    })
    longTaskObserver.observe({ type: 'longtask', buffered: true })
  } catch {
    longTaskObserver = null
  }
}

export function streamPerfReport(): Record<string, unknown> {
  const phaseReport: Record<string, { p50: number; p95: number; max: number; count: number }> = {}
  for (const [phase, s] of phaseStats) {
    const sorted = [...s.samples].sort((a, b) => a - b)
    phaseReport[phase] = {
      p50: +percentile(sorted, 50).toFixed(1),
      p95: +percentile(sorted, 95).toFixed(1),
      max: +s.max.toFixed(1),
      count: s.samples.length,
    }
  }

  const renderSorted = [...renderCountStats.samples].sort((a, b) => a - b)
  const memoSorted = [...memoHitRateStats.samples].sort((a, b) => a - b)

  let deltaRate = 0
  if (deltaTimestamps.length >= 2) {
    const span = (deltaTimestamps[deltaTimestamps.length - 1] - deltaTimestamps[0]) / 1000
    deltaRate = span > 0 ? deltaTimestamps.length / span : 0
  }

  let memTrend: { start: number; end: number; growth: number } | null = null
  if (memSamples.length >= 2) {
    const start = memSamples[0]
    const end = memSamples[memSamples.length - 1]
    memTrend = {
      start: +start.mb.toFixed(1),
      end: +end.mb.toFixed(1),
      growth: +(end.mb - start.mb).toFixed(1),
    }
  }

  return {
    phases: phaseReport,
    renderRows: {
      p50: percentile(renderSorted, 50),
      p95: percentile(renderSorted, 95),
      max: renderCountStats.max,
      count: renderCountStats.samples.length,
    },
    memoHitRate: {
      p50: +percentile(memoSorted, 50).toFixed(2),
      p95: +percentile(memoSorted, 95).toFixed(2),
      count: memoHitRateStats.samples.length,
    },
    deltaRate: +deltaRate.toFixed(1),
    baseline: baselineDeltaTotal > 0 ? { seq: baselineDeltaSeq, total: +baselineDeltaTotal.toFixed(1) } : null,
    memTrend,
  }
}

export function streamPerfEnabled(): boolean {
  return enabled
}

export function streamPerfReset(): void {
  phaseStats.clear()
  renderCountStats.samples = []
  renderCountStats.max = 0
  memoHitRateStats.samples = []
  deltaTimestamps = []
  baselineDeltaTotal = 0
  baselineDeltaSeq = -1
  memSamples = []
}

export function installStreamPerfGlobal(): void {
  if (typeof window === 'undefined') return
  installLongTaskMonitor()
  const g = window as unknown as Record<string, unknown>
  g.__streamPerf = {
    report: () => {
      const r = streamPerfReport()
      console.table(r.phases)
      console.log('[streamperf] 诊断:', {
        renderRows: r.renderRows,
        memoHitRate: r.memoHitRate,
        deltaRate: r.deltaRate,
        baseline: r.baseline,
        memTrend: r.memTrend,
      })
      return r
    },
    reset: streamPerfReset,
    enabled: () => enabled,
    lastDelta: () => lastDeltaSnapshot,
  }
}
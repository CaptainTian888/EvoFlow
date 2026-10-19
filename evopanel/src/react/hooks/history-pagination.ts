/**
 * 未超过此行数：普通文档流渲染历史（浏览器原生滚动，稳定、无估高空白、无 totalSize 跳变）。
 * 超过后启用虚拟列表，降低长会话 DOM 节点数。
 * 15 -> 30：虚拟列表的 measureElement 会在行滚入视口时更新 cache → totalSize 跳变 →
 * 滚动条 thumb 忽大忽小。flat 模式无此问题（scrollHeight 由真实 DOM 高度决定，天生稳定）。
 * 之前 30->15 是因 30 行 DOM 常驻卡，但那批卡顿根因（content-visibility 跳变、onScroll 同步
 * 布局查询、RO 抢 scrollTop）已逐一修复，30 行 flat 模式现可承受。
 */
export const HISTORY_FLAT_LIST_MAX_ROWS = 30

/** 距顶部小于此缓冲（px）时预取更早一页，避免滚到顶才加载。 */
export const HISTORY_LOAD_OLDER_TOP_BUFFER_MIN_PX = 320
export const HISTORY_LOAD_OLDER_TOP_BUFFER_MAX_PX = 720

/** WeChat-style prefetch buffer: ~1 viewport height from top, clamped. */
export function historyLoadOlderScrollBufferPx(viewportHeight: number): number {
  const vh = Math.max(1, Math.floor(Number(viewportHeight) || 0))
  return Math.max(
    HISTORY_LOAD_OLDER_TOP_BUFFER_MIN_PX,
    Math.min(HISTORY_LOAD_OLDER_TOP_BUFFER_MAX_PX, Math.floor(vh * 1.0)),
  )
}

export function shouldPrefetchOlderHistory(scroller: HTMLElement): boolean {
  return scroller.scrollTop < historyLoadOlderScrollBufferPx(scroller.clientHeight)
}

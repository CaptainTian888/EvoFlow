/**
 * 全局遮罩 → 隐藏原生浏览器 HWND。
 * 给 modal.js 等非 TS 入口用：begin/end 可同步排队，等 surface 加载后按序执行。
 */
let api = null
/** @type {Array<(m: typeof import('./browser-embed-surface.js')) => void>} */
const pending = []

void import('./browser-embed-surface.js')
  .then((m) => {
    api = m
    for (const op of pending) op(m)
    pending.length = 0
  })
  .catch(() => {})

function enqueue(op) {
  if (api) {
    op(api)
    return
  }
  pending.push(op)
}

/** @param {string} [reason] */
export function beginGlobalOverlay(reason = 'overlay') {
  enqueue((m) => m.beginGlobalOverlay(reason))
}

/** @param {string} [reason] */
export function endGlobalOverlay(reason = 'overlay') {
  enqueue((m) => m.endGlobalOverlay(reason))
}

/**
 * 挂上遮罩时 begin，返回只生效一次的 end。
 * @param {string} [reason]
 */
export function trackGlobalOverlay(reason = 'overlay') {
  beginGlobalOverlay(reason)
  let released = false
  return () => {
    if (released) return
    released = true
    endGlobalOverlay(reason)
  }
}

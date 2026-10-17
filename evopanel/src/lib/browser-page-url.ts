/**
 * WebView2 / Chromium 内部错误页地址。导航失败后 location.href 会变成这些，
 * 绝不能写回 pageUrl / 再 upsert，否则会陷入「反复打开 chrome-error」死循环。
 */
export function isBrowserInternalErrorUrl(url: string): boolean {
  const u = String(url || '').trim().toLowerCase()
  if (!u) return false
  return (
    u.startsWith('chrome-error:') ||
    u.startsWith('chrome://') ||
    u.startsWith('edge://') ||
    u.startsWith('devtools://') ||
    u.startsWith('about:neterror') ||
    u.includes('chromewebdata')
  )
}

/** 可写入标签 / 可交给 upsert 的地址；错误页则回退 fallback。 */
export function sanitizeBrowserPageUrl(url: string, fallback = ''): string {
  const raw = String(url || '').trim()
  if (!raw || isBrowserInternalErrorUrl(raw)) return String(fallback || '').trim()
  return raw
}

/** 是否值得对原生窗发起导航（空白页允许；错误页不允许）。 */
export function isNavigableBrowserUrl(url: string): boolean {
  const raw = String(url || '').trim()
  if (!raw) return false
  if (isBrowserInternalErrorUrl(raw)) return false
  return true
}

import { useEffect } from 'react'
import { beginGlobalOverlay, endGlobalOverlay } from '../../lib/browser-embed-overlay.js'

/** 全屏/半屏盖住聊天的 React 弹窗打开时隐藏原生浏览器 HWND。 */
export function useGlobalOverlayWhen(open: boolean, reason: string) {
  useEffect(() => {
    if (!open) return
    beginGlobalOverlay(reason)
    return () => endGlobalOverlay(reason)
  }, [open, reason])
}

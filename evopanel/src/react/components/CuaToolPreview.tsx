/**
 * CuaToolPreview —— 老对话流式路径（ToolCallList）的 Computer Use 工具预览卡。
 *
 * 数据来自 node_repl js 工具结果尾部的 `{evoflow-cua-display:...}` 标记
 * （chat-normalize.js 的 parseEvoflowCuaDisplay），对应 ZCode 面板
 * kind:"cua" 工具结果卡的平台等价实现：目标应用徽标（网关 /api/cua/app-icon
 * 按 locator 提取）+ 窗口截图（browser-snapshots 存储通道，点击放大）。
 */
import { useEffect, useState } from 'react'
import { showChatLightbox } from '../../lib/chat-lightbox.js'
import { apiUrlAsync } from '../../lib/api-client.js'
import {
  evoflowCuaAppKeyToIconRequest,
  resolveBrowserScreenshotSrcAsync,
} from '../../lib/chat-normalize.js'

const isTauri =
  typeof window !== 'undefined' &&
  // @ts-ignore
  !!(window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__)

export type EvoflowCuaDisplay = {
  status?: string
  images?: Array<{ url?: string; kb?: number }>
  target_app?: { app_key?: string; display_name?: string }
}

export type CuaToolPreviewProps = {
  display: EvoflowCuaDisplay
}

export function CuaToolPreview({ display }: CuaToolPreviewProps) {
  const [iconSrc, setIconSrc] = useState('')
  const [shotSrc, setShotSrc] = useState('')
  const [broken, setBroken] = useState(false)

  const appKey = String(display.target_app?.app_key || '').trim()
  const appName = String(display.target_app?.display_name || '').trim()
  const failed = display.status === 'failed'
  const shot = (display.images || []).find(
    (img) => typeof img?.url === 'string' && img.url,
  )

  useEffect(() => {
    let active = true
    setIconSrc('')
    setShotSrc('')
    setBroken(false)
    if (appKey) {
      const request = evoflowCuaAppKeyToIconRequest(appKey)
      if (request) {
        void (async () => {
          try {
            const response = await fetch(await apiUrlAsync('/api/cua/app-icon'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(request),
            })
            if (!response.ok) return
            const result = (await response.json()) as { iconDataUrl?: string } | null
            if (active && result?.iconDataUrl) setIconSrc(result.iconDataUrl)
          } catch {
            /* 图标失败回退通用图形 */
          }
        })()
      }
    }
    if (shot?.url) {
      const url = shot.url
      void (async () => {
        try {
          const resolved = await resolveBrowserScreenshotSrcAsync(url)
          if (active && resolved) setShotSrc(resolved)
        } catch {
          if (active) setBroken(true)
        }
      })()
    }
    return () => {
      active = false
    }
  }, [appKey, shot?.url])

  if (!appKey && !shot && !failed) return null

  return (
    <div className="msg-tool-block msg-tool-cua">
      {(iconSrc || appName) && (
        <div className="msg-tool-cua-target">
          {iconSrc ? (
            <img className="msg-tool-cua-icon" src={iconSrc} alt={appName || '目标应用'} />
          ) : null}
          {appName ? <span className="msg-tool-cua-app">{appName}</span> : null}
          <span
            className={
              failed ? 'msg-tool-cua-status msg-tool-cua-status--failed' : 'msg-tool-cua-status'
            }
          >
            {failed ? '操作失败' : '已完成'}
          </span>
        </div>
      )}
      {broken ? (
        <p className="msg-tool-screenshot-error">截图加载失败。</p>
      ) : shotSrc ? (
        <button
          type="button"
          className="msg-tool-screenshot-btn"
          title="放大"
          aria-label="打开截图预览"
          onClick={() => showChatLightbox(shotSrc)}
        >
          <img
            className="msg-tool-screenshot-img"
            src={shotSrc}
            alt={appName ? `${appName} 界面截图` : '电脑操作截图'}
            loading="lazy"
            onError={() => setBroken(true)}
          />
          <span className="msg-tool-screenshot-hint">点击放大</span>
        </button>
      ) : shot ? (
        <p className="msg-tool-screenshot-loading">正在加载截图…</p>
      ) : null}
    </div>
  )
}

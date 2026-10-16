/**
 * 原生 WebView 的显隐只走这里。规则对齐 ZCode 侧栏，不是多处各自 park。
 *
 * ZCode（Electron）把 `<webview>` 放进「当前选中的那个侧栏 tab」里：
 * - 侧栏折叠，或激活的不是这个 browser tab → 用户看不到 guest
 * - 可以有多个 browser tab（每条记录一个 id）
 * - 缓存分区只有一个：`persist:zcode-embedded-browser`，标签之间共用 cookie/缓存
 * - 布局是 DOM，guest 跟着槽位走，没有单独的屏幕坐标
 *
 * EvoFlow 的 WebView2 是主窗口里的一个子 HWND，不会跟着 React 隐藏。
 * 原生窗口也只有一个：`browser-embed-primary`（一份 WebView2 配置，一份缓存）。
 * 右栏里的 `browser:primary`、`browser:b-…`，以及每个会话各自缓存的那组标签，
 * 都是「哪一页在前台」的记录，不是多扇操作系统窗口。
 * 只有右栏展开且激活页是其中一个浏览器页时，这一扇窗才显示，并贴到该页槽位上。
 */
import {
  browserEmbedPark,
  browserEmbedSetBounds,
  browserEmbedUpsert,
  type BrowserEmbedInfo,
} from './browser-embed-client.js'
import { blog } from './browser-unified-log.js'
import { rightStageStore } from './right-stage/right-stage-store.js'

/** 与 browser-panel-store 的 NODE_REPL_BRIDGE_THREAD_ID 同一扇原生窗。 */
export const NATIVE_EMBED_THREAD_ID = 'evoflow-node-repl-bridge'

export type EmbedSlot = {
  x: number
  y: number
  width: number
  height: number
  viewportWidth?: number
  viewportHeight?: number
}

export type EmbedPlacement = {
  /** 空字符串 = 隐藏。非空 = 当前该显示的右栏浏览器 id。 */
  stageId: string
  reason: string
}

function browserStageIdFromSnapshot(): string {
  const snap = rightStageStore.getSnapshot()
  if (snap.collapsed || !snap.activeKey) return ''
  const tab =
    snap.tabs.find((item) => `${item.kind}:${item.id}` === snap.activeKey) || snap.surface
  if (!tab) return ''
  if (tab.kind === 'browser') return String(tab.id || 'primary')
  if (tab.kind === 'web-embed') {
    const data = tab.data || {}
    const ext = String(data.extensionId || data.extension_id || '').trim()
    if (!ext) return String(tab.id || 'primary')
  }
  return ''
}

let lastPlacementKey = ''
let visibleStageId = ''

export function currentEmbedPlacement(): EmbedPlacement {
  return { stageId: visibleStageId, reason: lastPlacementKey }
}

/** 右栏展开/换页/切会话/折叠之后调用。只有结果变了才动原生窗。 */
export function syncNativeEmbed(reason = 'right-stage') {
  const stageId = browserStageIdFromSnapshot()
  const key = stageId ? `show:${stageId}` : 'hide'
  if (key === lastPlacementKey) return
  lastPlacementKey = key
  visibleStageId = stageId
  const active = rightStageStore.getSnapshot().activeKey || '(none)'
  const line = `[browser-embed-surface] ${key} reason=${reason} active=${active}`
  console.info(line)
  blog('info', line)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('browser-embed-gate', {
        detail: { show: Boolean(stageId), id: stageId, reason },
      }),
    )
  }
  if (!stageId) void browserEmbedPark(NATIVE_EMBED_THREAD_ID)
}

/**
 * 槽位布局变了。只有这个 stageId 正是前台浏览器页时才把矩形交给原生窗。
 * 其它页报上来的尺寸直接丢掉，避免把已经隐藏的窗再贴回去。
 */
export function reportEmbedSlot(stageId: string, slot: EmbedSlot) {
  const id = String(stageId || '').trim()
  if (!id || id !== visibleStageId) return
  void browserEmbedSetBounds({
    threadId: NATIVE_EMBED_THREAD_ID,
    ...slot,
    present: true,
  })
}

/** 右栏还没量到槽位时的占位矩形。只用于把窗口建出来，不会在非浏览器页上显示。 */
export function estimateEmbedSlot(): EmbedSlot {
  const iw = window.innerWidth || 1280
  const ih = window.innerHeight || 800
  const width = Math.max(480, Math.floor(iw * 0.45))
  const height = Math.max(360, Math.floor(ih - 96))
  return {
    x: Math.max(0, Math.floor(iw - width - 12)),
    y: 64,
    width,
    height,
    viewportWidth: iw,
    viewportHeight: ih,
  }
}

function slotFor(stageId: string | undefined, slot: EmbedSlot | null | undefined): EmbedSlot {
  if (slot && slot.width >= 8 && slot.height >= 8) return slot
  return estimateEmbedSlot()
}

/**
 * 创建或导航那一扇原生窗。
 * 前台就是这个浏览器页：按槽位显示。
 * 否则只保证窗口存在（给 CDP），并保持隐藏。
 */
export async function ensureNativeEmbed(opts: {
  url?: string
  slot?: EmbedSlot | null
  stageId?: string
  reason: string
}): Promise<BrowserEmbedInfo | null> {
  const stageId = String(opts.stageId || '').trim()
  const present = Boolean(visibleStageId) && (!stageId || stageId === visibleStageId)
  const slot = slotFor(stageId, opts.slot)
  blog(
    'info',
    `[browser-embed-surface] ensure reason=${opts.reason} present=${present} stage=${stageId || '(any)'} visible=${visibleStageId || '(none)'}`,
  )
  const info = await browserEmbedUpsert({
    threadId: NATIVE_EMBED_THREAD_ID,
    url: opts.url,
    ...slot,
    respectManagedBounds: !present,
  })
  if (!present) void browserEmbedPark(NATIVE_EMBED_THREAD_ID)
  return info
}

rightStageStore.subscribe(() => {
  syncNativeEmbed('right-stage')
})
syncNativeEmbed('boot')

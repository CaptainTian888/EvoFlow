/**
 * 原生 WebView 的显隐只走这里。规则对齐 ZCode 侧栏，不是多处各自 park。
 *
 * ZCode（Electron）把 `<webview>` 放进「当前选中的那个侧栏 tab」里：
 * - 侧栏折叠，或激活的不是这个 browser tab → 用户看不到 guest
 * - 可以有多个 browser tab（每条记录一个 id）
 * - 缓存分区只有一个：`persist:zcode-embedded-browser`，标签之间共用 cookie/缓存
 * - 布局是 DOM，guest 跟着槽位走，没有单独的屏幕坐标
 *
 * EvoFlow 的 WebView2 是主窗口里的一个子 HWND，不会跟着 React 隐藏，
 * 也无法参与 CSS z-index。原生窗口也只有一个：`browser-embed-primary`。
 *
 * 显示条件（同时满足）：
 * 1. 右栏展开且激活页是浏览器页
 * 2. 没有盖住聊天区的全局遮罩（overlayDepth === 0）
 * 全局弹窗打开时隐藏 HWND，关掉后再按右栏状态贴回。
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
  overlayDepth: number
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
/** 右栏认为该显示的浏览器页 id（忽略遮罩）。贴位校验用这个。 */
let desiredStageId = ''
/** 遮罩为 0 且 desired 非空时真正显示的 id。 */
let visibleStageId = ''
let overlayDepth = 0

export function currentEmbedPlacement(): EmbedPlacement {
  return { stageId: visibleStageId, reason: lastPlacementKey, overlayDepth }
}

export function getGlobalOverlayDepth(): number {
  return overlayDepth
}

function placementKey(stageId: string, depth: number): string {
  if (depth > 0) return `hide:overlay:${depth}`
  return stageId ? `show:${stageId}` : 'hide'
}

/** 右栏展开/换页/切会话/折叠/遮罩变化之后调用。只有结果变了才动原生窗。 */
export function syncNativeEmbed(reason = 'right-stage') {
  const stageId = browserStageIdFromSnapshot()
  desiredStageId = stageId
  const canShow = Boolean(stageId) && overlayDepth === 0
  const shownId = canShow ? stageId : ''
  const key = placementKey(stageId, overlayDepth)
  if (key === lastPlacementKey) return
  lastPlacementKey = key
  visibleStageId = shownId
  const active = rightStageStore.getSnapshot().activeKey || '(none)'
  const line = `[browser-embed-surface] ${key} reason=${reason} active=${active} overlay=${overlayDepth}`
  console.info(line)
  blog('info', line)
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('browser-embed-gate', {
        detail: {
          show: Boolean(shownId),
          id: shownId,
          desiredId: stageId,
          overlayDepth,
          reason,
        },
      }),
    )
  }
  if (!shownId) void browserEmbedPark(NATIVE_EMBED_THREAD_ID)
}

/**
 * 盖住聊天区的全局遮罩打开。引用计数：嵌套弹窗各 begin 一次。
 * 原生 HWND 压不过 CSS，只能先藏起来。
 */
export function beginGlobalOverlay(reason = 'overlay') {
  overlayDepth += 1
  syncNativeEmbed(`overlay:${reason}:begin`)
}

/** 与 beginGlobalOverlay 成对。depth 不会掉到 0 以下。 */
export function endGlobalOverlay(reason = 'overlay') {
  if (overlayDepth <= 0) {
    overlayDepth = 0
    return
  }
  overlayDepth -= 1
  syncNativeEmbed(`overlay:${reason}:end`)
}

/**
 * 槽位布局变了。只有这个 stageId 正是前台浏览器页且无全局遮罩时才贴位。
 */
export function reportEmbedSlot(stageId: string, slot: EmbedSlot) {
  const id = String(stageId || '').trim()
  if (!id || id !== visibleStageId || overlayDepth > 0) return
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

function slotFor(_stageId: string | undefined, slot: EmbedSlot | null | undefined): EmbedSlot {
  if (slot && slot.width >= 8 && slot.height >= 8) return slot
  return estimateEmbedSlot()
}

/**
 * 创建或导航那一扇原生窗。
 * 前台就是这个浏览器页且无全局遮罩：按槽位显示。
 * 否则只保证窗口存在（给 CDP），并保持隐藏。
 */
export async function ensureNativeEmbed(opts: {
  url?: string
  slot?: EmbedSlot | null
  stageId?: string
  reason: string
}): Promise<BrowserEmbedInfo | null> {
  const stageId = String(opts.stageId || '').trim()
  const present =
    overlayDepth === 0 &&
    Boolean(desiredStageId) &&
    (!stageId || stageId === desiredStageId)
  const slot = slotFor(stageId, opts.slot)
  blog(
    'info',
    `[browser-embed-surface] ensure reason=${opts.reason} present=${present} stage=${stageId || '(any)'} visible=${visibleStageId || '(none)'} overlay=${overlayDepth}`,
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

/** Browser panel runtime state — module-level store shared by AG-UI hooks and the panel UI.
 *
 * Fed by browser tool-call events (see browser-panel-agui.ts) and consumed by
 * BrowserPanel.tsx via useSyncExternalStore. Also owns auto-showing the browser
 * right-stage surface when the agent opens a page.
 */

import { ensureNativeEmbed } from './browser-embed-surface.js'
import { parseBrowserLiveToolOutput } from './chat-normalize.js'
import { sanitizeBrowserPageUrl } from './browser-page-url.js'
import { rightStageStore } from './right-stage/right-stage-store.js'
import { normalizeRightStageKind } from './right-stage/right-stage-types.js'
import type { BrowserStreamFrameMetadata } from './browser-stream-client.js'
import type { BrowserTabSummary } from './browser-viewport-client.js'
import { dbgLog, dbgWarn } from './browser-debug-log.js'

export type BrowserPanelMode = 'evopanel' | 'headed' | 'cdp' | 'headless' | 'embed'

export type BrowserRuntimeState = {
  pageUrl: string
  /** Document title from the live page (toolbar / tab chip). */
  pageTitle: string
  /** Thread id extracted from the live stream path (`/api/threads/{tid}/browser-stream`). */
  streamThreadId: string
  browserMode?: BrowserPanelMode
  sharedBrowser: boolean
  /** True while a browser tool call is in flight (ZCode-style operation indicator). */
  operating: boolean
  operatingAction: string
  operatingToolCallId: string
  lastFrameMeta?: BrowserStreamFrameMetadata
  /** 引擎实时标签页（tabList 轮询结果） */
  tabs: BrowserTabSummary[]
  /** null = unknown (enable button); false only after engine reports no history. */
  canGoBack: boolean | null
  canGoForward: boolean | null
}

const EMPTY: BrowserRuntimeState = {
  pageUrl: '',
  pageTitle: '',
  streamThreadId: '',
  sharedBrowser: false,
  operating: false,
  operatingAction: '',
  operatingToolCallId: '',
  tabs: [],
  canGoBack: null,
  canGoForward: null,
}

let state: BrowserRuntimeState = { ...EMPTY }
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) {
    try {
      listener()
    } catch {
      // listener errors must not break the stream
    }
  }
}

function patch(next: Partial<BrowserRuntimeState>) {
  state = { ...state, ...next }
  emit()
}

export function subscribeBrowserRuntime(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getBrowserRuntimeSnapshot(): BrowserRuntimeState {
  return state
}

const DEFAULT_TID = ''

/**
 * Fixed engine session used by ``/api/browser/*`` (node-repl browser-use bridge).
 * The side panel must mount *this* WebView2 label so the user sees the same page
 * the agent drives — chat thread ids never reach the bridge execute path.
 */
export const NODE_REPL_BRIDGE_THREAD_ID = 'evoflow-node-repl-bridge'

/** Backend falls back to a literal ``evoflow`` session when the tool runtime has no
 * thread_id. That path never matches the panel's real thread, so reject it and keep
 * whatever real thread id we already have. */
const PLACEHOLDER_TIDS = new Set(['', 'evoflow', 'default', '__default__'])

export function extractThreadIdFromStreamPath(streamWs: string): string {
  const raw = String(streamWs || '').trim()
  if (!raw) return DEFAULT_TID
  const match = raw.match(/\/api\/threads\/([^/]+)\/browser-stream/i)
  if (!match?.[1]) return DEFAULT_TID
  let tid = ''
  try {
    tid = decodeURIComponent(match[1]) || ''
  } catch {
    tid = match[1]
  }
  return PLACEHOLDER_TIDS.has(tid.toLowerCase()) ? DEFAULT_TID : tid
}

/** Accept a thread id only when it looks like a real id (not a backend placeholder). */
export function acceptThreadId(tid: string | null | undefined): string {
  const raw = String(tid || '').trim()
  if (PLACEHOLDER_TIDS.has(raw.toLowerCase())) return DEFAULT_TID
  return raw
}

function newBrowserStageId(): string {
  return `b-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 打开或激活浏览器标签（不关掉其它 kind）。
 *  - 默认复用 `primary`（顶栏地球 / agent 驱动）
 *  - `forceNew: true` 时新建独立标签（加号菜单）
 */
function faviconUrlForPage(url: string): string {
  try {
    const parsed = new URL(url)
    if (!parsed.hostname || parsed.protocol === 'about:') return ''
    return `${parsed.origin}/favicon.ico`
  } catch {
    return ''
  }
}

function displayTitle(pageUrl: string, pageTitle: string): string {
  const titled = pageTitle.trim()
  if (titled) return titled
  const raw = pageUrl.trim()
  if (!raw) return '浏览器'
  try {
    return new URL(raw).hostname || '浏览器'
  } catch {
    return raw.slice(0, 40) || '浏览器'
  }
}

type TabHistory = { stack: string[]; index: number }

function readTabHistory(data: Record<string, unknown> | undefined | null): TabHistory {
  const stackRaw = data?.historyStack
  const stack = Array.isArray(stackRaw)
    ? stackRaw.map((u) => sanitizeBrowserPageUrl(String(u || '').trim())).filter(Boolean)
    : []
  if (!stack.length) return { stack: [], index: -1 }
  let index = typeof data?.historyIndex === 'number' ? Number(data.historyIndex) : stack.length - 1
  if (!Number.isFinite(index)) index = stack.length - 1
  index = Math.max(0, Math.min(Math.floor(index), stack.length - 1))
  return { stack, index }
}

function activeBrowserTabId(): string | null {
  const snap = rightStageStore.getSnapshot()
  const key = String(snap.activeKey || '')
  if (!key.startsWith('browser:')) return null
  return key.slice('browser:'.length) || null
}

function applyHistoryFlags(stack: string[], index: number) {
  patch({
    canGoBack: index > 0,
    canGoForward: index >= 0 && index < stack.length - 1,
  })
}

/** 站内导航：压入当前前台标签的逻辑历史栈（单 HWND 不能靠 window.history）。 */
export function pushBrowserTabHistory(url: string, pageTitle = ''): boolean {
  const tabId = activeBrowserTabId()
  if (!tabId) return false
  const clean = sanitizeBrowserPageUrl(url)
  if (!clean) return false
  const tab = rightStageStore.findTab(`browser:${tabId}`)
  if (!tab) return false
  const { stack, index } = readTabHistory(tab.data)
  let truncated = stack.slice(0, Math.max(0, index + 1))
  // 旧标签没有栈时，先把当前 pageUrl 垫进栈底，后退才回得到。
  if (!truncated.length) {
    const cur = sanitizeBrowserPageUrl(String(tab.data?.pageUrl || '').trim())
    if (cur && cur !== clean) truncated = [cur]
  }
  if (truncated[truncated.length - 1] === clean) {
    applyHistoryFlags(truncated, truncated.length - 1)
    return true
  }
  truncated.push(clean)
  const newIndex = truncated.length - 1
  const isBlank = clean === 'about:blank'
  rightStageStore.patchTab(`browser:${tabId}`, {
    title: isBlank ? '新标签页' : displayTitle(clean, pageTitle),
    data: {
      pageUrl: isBlank ? 'about:blank' : clean,
      faviconUrl: isBlank ? '' : faviconUrlForPage(clean),
      historyStack: truncated,
      historyIndex: newIndex,
    },
  })
  patch({
    pageUrl: isBlank ? '' : clean,
    pageTitle: String(pageTitle || '').trim(),
    canGoBack: newIndex > 0,
    canGoForward: false,
  })
  return true
}

/** 逻辑栈后退/前进。返回目标 URL；无法移动时返回 null。 */
export function stepBrowserTabHistory(delta: -1 | 1): string | null {
  const tabId = activeBrowserTabId()
  if (!tabId) return null
  const tab = rightStageStore.findTab(`browser:${tabId}`)
  if (!tab) return null
  const { stack, index } = readTabHistory(tab.data)
  const next = index + delta
  if (next < 0 || next >= stack.length) return null
  const url = stack[next]
  const isBlank = !url || url === 'about:blank'
  rightStageStore.patchTab(`browser:${tabId}`, {
    title: isBlank ? '新标签页' : displayTitle(url, ''),
    data: {
      pageUrl: isBlank ? 'about:blank' : url,
      faviconUrl: isBlank ? '' : faviconUrlForPage(url),
      historyStack: stack,
      historyIndex: next,
    },
  })
  patch({
    pageUrl: isBlank ? '' : url,
    canGoBack: next > 0,
    canGoForward: next < stack.length - 1,
  })
  return url
}

/** 把当前网页标题/图标写到右侧前台浏览器标签上（单 HWND，每标签各自记 URL）。 */
function syncBrowserStageChrome(pageUrl: string, pageTitle: string) {
  const snap = rightStageStore.getSnapshot()
  const browsers = snap.tabs.filter((t) => normalizeRightStageKind(t.kind) === 'browser')
  if (!browsers.length) return
  const active =
    browsers.find((t) => `browser:${t.id}` === snap.activeKey) || browsers[0]
  // 错误页 URL 不写进标签，保留该标签已有地址。
  const prevUrl = String(active.data?.pageUrl || '').trim()
  const url = sanitizeBrowserPageUrl(pageUrl, prevUrl)
  if (!url && String(pageUrl || '').trim()) return
  const isBlank = !url || url === 'about:blank'
  // 只改 title/pageUrl/favicon，保留 historyStack / historyIndex。
  rightStageStore.patchTab(`browser:${active.id}`, {
    title: isBlank ? '新标签页' : displayTitle(url, pageTitle),
    data: {
      pageUrl: isBlank ? 'about:blank' : url,
      faviconUrl: isBlank ? '' : faviconUrlForPage(url),
    },
  })
}

/**
 * 原生 WebView2 只有一扇窗。右侧可以有多个 browser 标签，各自在 tab.data.pageUrl
 * 里记当前页。切签时把原生窗导航到该标签保存的地址，避免「新标签还是旧网页」。
 *
 * 切签/新标签时这里不带实测槽位：ensureNativeEmbed 会 managed-only 导航并保持停靠，
 * 由前台 BrowserPanel 的 reportEmbedSlot 再贴回面板区域（避免估算矩形盖住标签条）。
 */
let lastActiveBrowserKey = ''

function applyStageBrowserSurface(tabId: string, pageUrl: string, pageTitle: string, reason: string) {
  const raw = String(pageUrl || '').trim() || 'about:blank'
  const url = sanitizeBrowserPageUrl(raw, 'about:blank') || 'about:blank'
  const title = String(pageTitle || '').trim()
  const tab = rightStageStore.findTab(`browser:${tabId}`)
  const { stack, index } = readTabHistory(tab?.data)
  patch({
    pageUrl: url === 'about:blank' ? '' : url,
    pageTitle: title === '新标签页' ? '' : title,
    canGoBack: index > 0,
    canGoForward: index >= 0 && index < stack.length - 1,
  })
  void ensureNativeEmbed({
    url,
    stageId: tabId,
    reason,
    // 切签/新标签用 replace，后退只走「本标签内」历史，不串到其它标签页。
    replace: reason === 'stage-switch' || reason === 'force-new',
  })
}

function onRightStageBrowserChange() {
  const snap = rightStageStore.getSnapshot()
  const key = String(snap.activeKey || '')
  if (!key.startsWith('browser:')) {
    lastActiveBrowserKey = ''
    return
  }
  if (key === lastActiveBrowserKey) return
  const prev = lastActiveBrowserKey
  lastActiveBrowserKey = key
  if (!prev) return
  const tab = snap.tabs.find((t) => `browser:${t.id}` === key)
  if (!tab) return
  const url =
    sanitizeBrowserPageUrl(String(tab.data?.pageUrl || '').trim(), 'about:blank') || 'about:blank'
  const title = String(tab.title || '').trim()
  dbgLog(`[browser-panel-store] stage switch ${prev} → ${key} url=${url}`)
  applyStageBrowserSurface(tab.id, url, title, 'stage-switch')
}

rightStageStore.subscribe(onRightStageBrowserChange)

export function ensureBrowserStage(opts?: {
  forceNew?: boolean
  sessionKey?: string
  title?: string
  id?: string
}) {
  const sessionKey = String(opts?.sessionKey || '').trim() || undefined
  const id = opts?.forceNew
    ? newBrowserStageId()
    : String(opts?.id || 'primary').trim() || 'primary'
  const existing = rightStageStore.findTab(`browser:${id}`)

  if (opts?.forceNew) {
    // 新标签：空白页。单 HWND 必须立刻 navigate，否则仍显示上一标签的页面。
    rightStageStore.show({
      kind: 'browser',
      id,
      title: '新标签页',
      layout: 'wide',
      sessionKey,
      data: {
        pageUrl: 'about:blank',
        faviconUrl: '',
        historyStack: ['about:blank'],
        historyIndex: 0,
      },
    })
    lastActiveBrowserKey = `browser:${id}`
    applyStageBrowserSurface(id, 'about:blank', '', 'force-new')
    return
  }

  rightStageStore.show({
    kind: 'browser',
    id,
    title: String(opts?.title || '').trim() || existing?.title || '浏览器',
    layout: 'wide',
    sessionKey,
    data: existing?.data ? { ...existing.data } : {},
  })
  lastActiveBrowserKey = `browser:${id}`
}

/** 引擎标签页列表写入（面板轮询 tabList 后调用）。 */
export function setBrowserTabs(tabs: BrowserTabSummary[]) {
  const list = Array.isArray(tabs) ? tabs : []
  const next: Partial<BrowserRuntimeState> = { tabs: list }
  const active = list.find((t) => t.active) || list[0]
  if (active) {
    const url = sanitizeBrowserPageUrl(String(active.url || '').trim())
    const title = String(active.title || '').trim()
    if (url) next.pageUrl = url
    if (title) next.pageTitle = title
  }
  patch(next)
  syncBrowserStageChrome(next.pageUrl || state.pageUrl, next.pageTitle || state.pageTitle)
}

/** 只关浏览器这一页，其它 right-stage 标签保留。 */
export function closeBrowserStage(id = 'primary') {
  const tabId = String(id || 'primary').trim() || 'primary'
  rightStageStore.closeTab(`browser:${tabId}`)
}

/** Publish the panel's *real* thread id (from the chat session) so the browser
 * tool metadata can be validated against it. Called by ChatApp on every
 * browser tool event. */
export function setBrowserPanelThreadId(threadId: string | null | undefined): boolean {
  const tid = acceptThreadId(threadId)
  if (!tid || tid === state.streamThreadId) return false
  dbgLog(`[browser-panel-store] set threadId=${tid} (was ${state.streamThreadId || '(empty)'})`)
  patch({ streamThreadId: tid })
  return true
}

/** Patch runtime from a direct browser-command/tab response (user-initiated
 *  action that did NOT go through the AG-UI tool stream). Without this, typing
 *  a URL into the address bar would succeed at the backend but the panel would
 *  not refresh because it only listened for tool-result events. */
export function applyBrowserCommandResponse(input: {
  threadId?: string
  pageUrl?: string
  pageTitle?: string
  streamWs?: string
  canGoBack?: boolean
  canGoForward?: boolean
  /** 为 true 时压入当前标签逻辑历史（地址栏/站内导航）；切签后退不要传。 */
  pushHistory?: boolean
}): boolean {
  const next: Partial<BrowserRuntimeState> = {}
  const tid = acceptThreadId(input.threadId)
  if (tid) next.streamThreadId = tid
  const pageUrl = sanitizeBrowserPageUrl(input.pageUrl || '', state.pageUrl)
  if (pageUrl) next.pageUrl = pageUrl
  if (input.pageTitle !== undefined) {
    next.pageTitle = String(input.pageTitle || '').trim()
  }
  // 工具栏以后退栈为准；引擎 canGo* 不再覆盖逻辑栈（除非未 push 且显式传入）。
  if (!input.pushHistory) {
    if (typeof input.canGoBack === 'boolean') next.canGoBack = input.canGoBack
    if (typeof input.canGoForward === 'boolean') next.canGoForward = input.canGoForward
  }
  if (!Object.keys(next).length && !input.pushHistory) return false
  dbgLog(
    `[browser-panel-store] apply browser-command response thread=${tid || state.streamThreadId} ` +
      `url=${pageUrl || '(unchanged)'} title=${next.pageTitle ?? '(unchanged)'} push=${Boolean(input.pushHistory)}`,
  )
  if (Object.keys(next).length) patch(next)
  // 已有浏览器标签时绝不能 ensureBrowserStage()：默认会激活 primary，
  // 把当前标签（如第二个新标签）上的导航写到第一个标签上。
  const snap = rightStageStore.getSnapshot()
  const hasBrowser = snap.tabs.some((t) => normalizeRightStageKind(t.kind) === 'browser')
  if (!hasBrowser) ensureBrowserStage()
  if (input.pushHistory && pageUrl) {
    pushBrowserTabHistory(pageUrl, state.pageTitle)
  } else {
    syncBrowserStageChrome(state.pageUrl, state.pageTitle)
  }
  return true
}

export function notifyBrowserToolStart(
  toolCallId: string,
  argsText?: string | null,
  opts?: { toolName?: string; forceOpen?: boolean },
): boolean {
  const toolName = String(opts?.toolName || '').trim().toLowerCase()
  const isNodeRepl = toolName === 'mcp__node_repl__js'
  const { action, url } = parseBrowserToolArgs(argsText)
  // node_repl 只有代码里真的出现浏览器 API 才自动拉起面板；纯数据处理 JS 保持侧栏安静。
  const nodeReplBrowser = isNodeRepl && nodeReplArgsTouchBrowser(argsText)
  dbgLog(
    `[browser-panel-store] tool start toolCallId=${toolCallId} tool=${toolName || '(n/a)'} ` +
      `action=${action} url=${url || '(none)'} browserIntent=${nodeReplBrowser} argsText=${(argsText || '').slice(0, 200)}`,
  )
  // node-repl / browser-use always drives the shared bridge WebView2. Bind the
  // panel to that session *before* ensureBrowserStage so the embed host mounts
  // the same HWND the agent is about to control.
  if (isNodeRepl) {
    patch({ streamThreadId: NODE_REPL_BRIDGE_THREAD_ID })
  }
  patch({
    operating: true,
    operatingAction: action || (isNodeRepl ? 'node_repl' : ''),
    operatingToolCallId: String(toolCallId || '').trim(),
  })
  // For page-opening actions (and node_repl calls whose code drives the browser),
  // raise the right stage *before* the result arrives so the user can see the live
  // panel mount while the agent is still working.
  if (
    opts?.forceOpen ||
    nodeReplBrowser ||
    action === 'open' ||
    action === 'navigate' ||
    action === 'snapshot'
  ) {
    ensureBrowserStage()
  }
  // Publish the target URL now rather than waiting for the tool result. The
  // embedded browser mounts as soon as the stage opens, so a late URL meant the
  // window rendered on `about:blank` until the agent finished.
  if (url && /^https?:\/\//i.test(url)) {
    if (url !== state.pageUrl) {
      dbgLog(`[browser-panel-store] seed pageUrl=${url} (from tool start)`)
      patch({ pageUrl: url })
    }
  }
  return true
}

export function notifyBrowserToolResult(
  toolCallId: string,
  resultText?: string | null,
  opts?: { nodeReplBrowser?: boolean },
): boolean {
  const live = parseBrowserLiveToolOutput(resultText)
  const liveSummary = live
    ? { mode: live.mode, pageUrl: live.pageUrl, streamWs: live.streamWs, headed: live.headed }
    : null
  dbgLog(
    `[browser-panel-store] tool result toolCallId=${toolCallId} live=${JSON.stringify(liveSummary)} raw=${(resultText || '').slice(0, 160)}`,
  )
  if (resultText && !live) {
    // node-repl results are SDK stdout / structured objects, not browser_live —
    // that is expected. Keep the panel bound to the bridge session anyway.
    dbgWarn(`[browser-panel-store] live parse returned null for toolCallId=${toolCallId}`)
  }
  const next: Partial<BrowserRuntimeState> = {
    operating: state.operatingToolCallId === String(toolCallId || '').trim() ? false : state.operating,
  }
  // If we are already on the node-repl bridge session (or just opened for it),
  // keep the panel up even without a browser_live payload — but only when this
  // call actually drove the browser; a pure-JS node_repl result must not re-raise
  // a panel the user closed.
  const onBridge =
    state.streamThreadId === NODE_REPL_BRIDGE_THREAD_ID ||
    state.operatingAction === 'node_repl'
  if (onBridge) {
    next.streamThreadId = NODE_REPL_BRIDGE_THREAD_ID
    next.browserMode = next.browserMode || state.browserMode || 'embed'
    next.sharedBrowser = false
    if (opts?.nodeReplBrowser !== false) ensureBrowserStage()
  }
  if (live) {
    const backendTid = extractThreadIdFromStreamPath(
      String((live as { streamWs?: string }).streamWs || ''),
    )
    if (backendTid) {
      next.streamThreadId = backendTid
    } else if (!onBridge) {
      dbgWarn(
        `[browser-panel-store] backend streamWs=${String((live as { streamWs?: string }).streamWs || '')} has placeholder thread — keeping real threadId=${state.streamThreadId || '(empty)'}`,
      )
    }
    const pageUrl = sanitizeBrowserPageUrl(String((live as { pageUrl?: string }).pageUrl || '').trim())
    if (pageUrl) next.pageUrl = pageUrl
    const mode = String((live as { mode?: string }).mode || '').trim()
    if (
      mode === 'evopanel' ||
      mode === 'headed' ||
      mode === 'cdp' ||
      mode === 'headless' ||
      mode === 'embed'
    ) {
      next.browserMode = mode
    }
    const headed = Boolean((live as { headed?: boolean | string }).headed)
    // In-process Playwright engine: browser lives in EvoPanel, *not* on the
    // user's desktop. Only legacy headed / external CDP / WebView2 embed share
    // the user's own browser, so we suppress the shared-browser flag there.
    next.sharedBrowser = headed || mode === 'headed' || mode === 'cdp' || mode === 'embed'
    if (mode === 'evopanel' || mode === 'embed' || onBridge) next.sharedBrowser = false
    // Agent opened a page → bring the browser stage up (ZCode side-pane behavior).
    if (pageUrl || backendTid || onBridge) ensureBrowserStage()
  }
  patch(next)
  if (next.pageUrl || state.pageUrl) {
    syncBrowserStageChrome(state.pageUrl, state.pageTitle)
  }
  return Boolean(live) || onBridge
}

export function notifyBrowserToolEnd(toolCallId: string): boolean {
  if (state.operatingToolCallId && state.operatingToolCallId !== String(toolCallId || '').trim()) {
    return false
  }
  patch({ operating: false, operatingAction: '', operatingToolCallId: '' })
  return true
}

export function notifyBrowserFrameMetadata(meta?: BrowserStreamFrameMetadata) {
  if (!meta) return
  patch({ lastFrameMeta: meta })
}

/** Pull URL intents out of node-repl ``code`` (browsers.open / navigate / tabs.new). */
function extractUrlFromNodeReplCode(code: string): string {
  const raw = String(code || '')
  if (!raw) return ''
  const openMatch = raw.match(
    /(?:browsers\.open|tabs\.new|\.navigate|agent\.browsers\.open)\(\s*["'`]([^"'`]+)["'`]/,
  )
  return String(openMatch?.[1] || '').trim()
}

/** browser-use 技能写进 node_repl 代码的浏览器 API 面（control-browser SKILL 形状：
 * agent.browsers.* / tabs.new / tab.navigate / b.execute({method:...}) / 桥符号）。
 * 刻意排除 computer-use（agent.computerUse.*）——桌面控制没有浏览器面板可展示；
 * 也排除常见数据处理词形（tabs 数组的 .map/.forEach/.length 不会命中）。
 * 召回优先：漏判的浏览器调用还有后端 browser-panel-request（CDP 真驱动 WebView2
 * 时必发）兜底拉起面板，不会出现「浏览器动了、面板不在」。 */
const NODE_REPL_BROWSER_INTENT_RE = new RegExp(
  [
    'agent\\.browsers\\b',
    '\\bbrowsers\\s*\\.\\s*(open|get|getForUrl|getDefault|list)\\b',
    "\\btabs?\\s*\\.\\s*(new|get|list|finalize|activate|claim|close|reload|navigate|snapshot|screenshot|click|fill|type|press|scroll|hover|select|check|drag|back|forward|evaluate|waitFor|getState|elementInfo)\\s*\\(",
    '\\.\\s*navigate\\s*\\(',
    '\\.\\s*(newTab|activateTab|claimTab|browserViewportSet)\\s*\\(',
    // \\? 吃掉 JSON 转义引号前的反斜杠（argsText 里是 method: \"navigate\"）
    "\\bmethod\\s*:\\s*\\\\?[\"'`]?(?:navigate|back|forward|reload|snapshot|click|fill|type|press|scroll|hover|select|check|drag|screenshot|evaluate|waitFor|elementInfo|getState|close|newTab|activateTab|claimTab|browserViewportSet)\\b",
    'browser-control-bridge',
  ].join('|'),
  'i',
)

/** Does this node_repl ``js`` tool args payload drive the browser?
 *  Runs on the raw (possibly partial, JSON-escaped) args text — streamed
 *  TOOL_CALL_ARGS chunks must already trigger the intent, not only complete JSON. */
export function nodeReplArgsTouchBrowser(argsText?: string | null): boolean {
  const raw = String(argsText || '')
  if (!raw) return false
  return NODE_REPL_BROWSER_INTENT_RE.test(raw)
}

/** Pull the requested URL out of the tool arguments, tolerating a partial
 *  (streamed, truncated) JSON payload. The embedded browser boots as soon as the
 *  stage opens — which happens on tool *start* — so waiting for the tool result to
 *  reveal the URL left the window sitting on `about:blank` for the whole time the
 *  agent was working. */
function parseBrowserToolArgs(argsText?: string | null): { action: string; url: string } {
  const raw = String(argsText || '').trim()
  if (!raw) return { action: '', url: '' }
  try {
    const args = JSON.parse(raw) as { action?: string; url?: string; code?: string }
    const action = String(args?.action || '').trim().toLowerCase()
    let url = String(args?.url || '').trim()
    if (!url && args?.code) url = extractUrlFromNodeReplCode(args.code)
    return { action, url }
  } catch {
    const action = String(raw.match(/"action"\s*:\s*"([^"]+)"/i)?.[1] || '').trim().toLowerCase()
    // Streamed args can end mid-string, so accept whatever was captured so far.
    let url = String(raw.match(/"url"\s*:\s*"([^"]*)/i)?.[1] || '').trim()
    if (!url) url = extractUrlFromNodeReplCode(raw)
    return { action, url }
  }
}

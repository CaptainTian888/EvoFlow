/** Browser panel runtime state — module-level store shared by AG-UI hooks and the panel UI.
 *
 * Fed by browser tool-call events (see browser-panel-agui.ts) and consumed by
 * BrowserPanel.tsx via useSyncExternalStore. Also owns auto-showing the browser
 * right-stage surface when the agent opens a page.
 */

import './browser-embed-surface.js'
import { parseBrowserLiveToolOutput } from './chat-normalize.js'
import { rightStageStore } from './right-stage/right-stage-store.js'
import type { BrowserStreamFrameMetadata } from './browser-stream-client.js'
import type { BrowserTabSummary } from './browser-viewport-client.js'
import { dbgLog, dbgWarn } from './browser-debug-log.js'

export type BrowserPanelMode = 'evopanel' | 'headed' | 'cdp' | 'headless' | 'embed'

export type BrowserRuntimeState = {
  pageUrl: string
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
}

const EMPTY: BrowserRuntimeState = {
  pageUrl: '',
  streamThreadId: '',
  sharedBrowser: false,
  operating: false,
  operatingAction: '',
  operatingToolCallId: '',
  tabs: [],
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
  rightStageStore.show({
    kind: 'browser',
    id,
    title: String(opts?.title || '').trim() || '浏览器',
    layout: 'wide',
    sessionKey,
    data: {},
  })
}

/** 引擎标签页列表写入（面板轮询 tabList 后调用）。 */
export function setBrowserTabs(tabs: BrowserTabSummary[]) {
  patch({ tabs: Array.isArray(tabs) ? tabs : [] })
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
}): boolean {
  const next: Partial<BrowserRuntimeState> = {}
  const tid = acceptThreadId(input.threadId)
  if (tid) next.streamThreadId = tid
  const pageUrl = String(input.pageUrl || '').trim()
  if (pageUrl) next.pageUrl = pageUrl
  if (!Object.keys(next).length) return false
  dbgLog(
    `[browser-panel-store] apply browser-command response thread=${tid || state.streamThreadId} ` +
      `url=${pageUrl || '(unchanged)'}`,
  )
  patch(next)
  // Make sure the browser stage is mounted; it may have been opened straight
  // from the address bar without the user clicking the toggle first.
  ensureBrowserStage()
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
  dbgLog(
    `[browser-panel-store] tool start toolCallId=${toolCallId} tool=${toolName || '(n/a)'} ` +
      `action=${action} url=${url || '(none)'} argsText=${(argsText || '').slice(0, 200)}`,
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
  // For page-opening actions (and every node-repl browser call), raise the
  // right stage *before* the result arrives so the user can see the live
  // panel mount while the agent is still working.
  if (
    opts?.forceOpen ||
    isNodeRepl ||
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

export function notifyBrowserToolResult(toolCallId: string, resultText?: string | null): boolean {
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
  // keep the panel up even without a browser_live payload.
  const onBridge =
    state.streamThreadId === NODE_REPL_BRIDGE_THREAD_ID ||
    state.operatingAction === 'node_repl'
  if (onBridge) {
    next.streamThreadId = NODE_REPL_BRIDGE_THREAD_ID
    next.browserMode = next.browserMode || state.browserMode || 'embed'
    next.sharedBrowser = false
    ensureBrowserStage()
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
    const pageUrl = String((live as { pageUrl?: string }).pageUrl || '').trim()
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

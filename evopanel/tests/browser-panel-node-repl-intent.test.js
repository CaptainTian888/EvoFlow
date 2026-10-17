import { describe, expect, it, beforeEach } from 'vitest'
import {
  NODE_REPL_BRIDGE_THREAD_ID,
  nodeReplArgsTouchBrowser,
  notifyBrowserToolEnd,
  notifyBrowserToolResult,
  notifyBrowserToolStart,
  setBrowserPanelThreadId,
} from '../src/lib/browser-panel-store.js'
import { rightStageStore } from '../src/lib/right-stage/right-stage-store.js'
import { syncBrowserPanelFromAgUiEvent } from '../src/lib/browser-panel-agui.js'

function browserTabOpen() {
  return rightStageStore.getSnapshot().tabs.some((t) => t.kind === 'browser')
}

function argsOf(code) {
  return JSON.stringify({ code })
}

describe('nodeReplArgsTouchBrowser', () => {
  it('matches control-browser skill shapes', () => {
    expect(nodeReplArgsTouchBrowser(argsOf('const b = await agent.browsers.getForUrl("https://x/")'))).toBe(true)
    expect(nodeReplArgsTouchBrowser(argsOf('const b = await agent.browsers.open("https://x/")'))).toBe(true)
    expect(nodeReplArgsTouchBrowser(argsOf('const t = await tabs.new("https://x/")'))).toBe(true)
    expect(nodeReplArgsTouchBrowser(argsOf('await tab.navigate("https://x/")'))).toBe(true)
    expect(nodeReplArgsTouchBrowser(argsOf('const s = await b.execute({ method: "screenshot", params: {} })'))).toBe(true)
    expect(nodeReplArgsTouchBrowser(argsOf('await b.execute({ method: "navigate", url: "https://x/" })'))).toBe(true)
    expect(nodeReplArgsTouchBrowser(argsOf('const br = Symbol.for("zcode.node-repl.browser-control-bridge")'))).toBe(true)
    expect(nodeReplArgsTouchBrowser(argsOf('await tab.snapshot(); await tab.click("@e2")'))).toBe(true)
  })

  it('ignores pure data-processing JS and computer-use calls', () => {
    expect(nodeReplArgsTouchBrowser(argsOf('const xs = [1,2,3].map((n) => n * 2); JSON.stringify(xs)'))).toBe(false)
    expect(nodeReplArgsTouchBrowser(argsOf('const tabs = rows.filter(r => r.active); tabs.forEach(t => out.push(t.title))'))).toBe(false)
    expect(nodeReplArgsTouchBrowser(argsOf('const res = await fetch("https://api.x/data"); return await res.json()'))).toBe(false)
    // computer-use 走桌面桥，没有浏览器面板可展示
    expect(nodeReplArgsTouchBrowser(argsOf('const app = await agent.computerUse.getApp("Notes"); await agent.computerUse.computer.screenshot()'))).toBe(false)
    expect(nodeReplArgsTouchBrowser('')).toBe(false)
    expect(nodeReplArgsTouchBrowser(null)).toBe(false)
  })

  it('triggers on partial (streamed) args', () => {
    // TOOL_CALL_ARGS 分片的 argsText 是已累积但未闭合的 JSON——
    // 截断点只要落在完整 token 之后就该命中；半截单词由下一个分片补全。
    expect(nodeReplArgsTouchBrowser('{"code": "const b = await agent.browsers.getFor"')).toBe(true)
    expect(
      nodeReplArgsTouchBrowser('{"code": "const b = await b.execute({ method: \\"navigate\\", url: \\"https'),
    ).toBe(true)
    expect(nodeReplArgsTouchBrowser('{"code": "await tabs.new(\\"https')).toBe(true)
  })
})

describe('browser panel auto-open gating', () => {
  beforeEach(() => {
    rightStageStore.hideAll()
    setBrowserPanelThreadId(NODE_REPL_BRIDGE_THREAD_ID)
  })

  it('pure-JS node_repl call does not open the browser stage', () => {
    const toolCalls = new Map([['t1', { toolCallId: 't1', toolCallName: 'mcp__node_repl__js', argsText: argsOf('const sum = 1 + 2; nodeRepl.write(sum)') }]])
    expect(syncBrowserPanelFromAgUiEvent({ type: 'TOOL_CALL_START', toolCallId: 't1', toolCallName: 'mcp__node_repl__js' }, toolCalls)).toBe(true)
    expect(syncBrowserPanelFromAgUiEvent({ type: 'TOOL_CALL_END', toolCallId: 't1' }, toolCalls)).toBe(true)
    expect(browserTabOpen()).toBe(false)
  })

  it('browser-driving node_repl call opens the stage at start', () => {
    const toolCalls = new Map([['t2', { toolCallId: 't2', toolCallName: 'mcp__node_repl__js', argsText: argsOf('const b = await agent.browsers.getForUrl("https://example.com/"); await b.execute({ method: "navigate", url: "https://example.com/" })') }]])
    syncBrowserPanelFromAgUiEvent({ type: 'TOOL_CALL_START', toolCallId: 't2', toolCallName: 'mcp__node_repl__js' }, toolCalls)
    expect(browserTabOpen()).toBe(true)
  })

  it('empty START args stay quiet; streamed ARGS with browser code open the stage', () => {
    const toolCalls = new Map([['t3', { toolCallId: 't3', toolCallName: 'mcp__node_repl__js', argsText: '' }]])
    syncBrowserPanelFromAgUiEvent({ type: 'TOOL_CALL_START', toolCallId: 't3', toolCallName: 'mcp__node_repl__js' }, toolCalls)
    expect(browserTabOpen()).toBe(false)
    toolCalls.get('t3').argsText = argsOf('await tabs.new("https://example.com/")')
    syncBrowserPanelFromAgUiEvent({ type: 'TOOL_CALL_ARGS', toolCallId: 't3' }, toolCalls)
    expect(browserTabOpen()).toBe(true)
  })

  it('pure-JS result does not re-raise a closed panel', () => {
    rightStageStore.closeTab('browser:primary')
    expect(browserTabOpen()).toBe(false)
    // 返回值语义是「绑定/结果有变化」（驱动一次重渲染），桥会话上恒为 true；
    // 关键断言是面板不再被拽回来。
    const changed = notifyBrowserToolResult('t1', 'plain stdout: 42', { nodeReplBrowser: false })
    expect(changed).toBe(true)
    expect(browserTabOpen()).toBe(false)
    notifyBrowserToolEnd('t1')
  })

  it('browser-driving result without browser_live payload still keeps the stage', () => {
    rightStageStore.closeTab('browser:primary')
    const changed = notifyBrowserToolResult('t2', 'navigated ok', { nodeReplBrowser: true })
    expect(changed).toBe(true)
    expect(browserTabOpen()).toBe(true)
    notifyBrowserToolEnd('t2')
  })

  it('genuine browser tools still force-open (unchanged)', () => {
    notifyBrowserToolStart('t4', JSON.stringify({ action: 'click' }), { toolName: 'browser', forceOpen: true })
    expect(browserTabOpen()).toBe(true)
    notifyBrowserToolEnd('t4')
  })
})

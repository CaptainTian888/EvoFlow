import { describe, it, expect } from 'vitest'
import {
  parseEvoflowCuaDisplay,
  inferEvoflowCuaDisplayFromOutput,
  resolveEvoflowCuaDisplay,
  stripEvoflowCuaDisplayMarker,
  evoflowCuaAppKeyToIconRequest,
  normalizeChatToolPayloadToEntries,
  maybeSlimToolOutputForUi,
  messagesToDisplayRows,
  EVOFLOW_CUA_DISPLAY_PREFIX,
} from '../src/lib/chat-normalize.js'

function buildMarker(payload) {
  return EVOFLOW_CUA_DISPLAY_PREFIX + JSON.stringify(payload) + '}'
}

describe('parseEvoflowCuaDisplay', () => {
  it('parses the trailing marker with target app, images and status', () => {
    const payload = {
      status: 'success',
      images: [{ url: '/api/threads/t1/browser-snapshots/abc123', kb: 63 }],
      target_app: {
        app_key: 'windows-exe:d:\\app\\zcode\\zcode.exe',
        display_name: 'ZCode',
      },
    }
    const output = [
      'app: ZCode pid=1 "ZCode"',
      'window: "ZCode" window_id=199188',
      'elements (400):',
      ' [0] window ZCode (focused)',
      '',
      '[Screenshot captured: /api/threads/t1/browser-snapshots/abc123 (63KB) — shown in the chat UI.]',
      '',
      buildMarker(payload),
    ].join('\n')
    const parsed = parseEvoflowCuaDisplay(output)
    expect(parsed).toEqual(payload)
  })

  it('returns null for outputs without a marker', () => {
    expect(parseEvoflowCuaDisplay('plain tool output\nline two')).toBeNull()
    expect(parseEvoflowCuaDisplay('')).toBeNull()
    expect(parseEvoflowCuaDisplay(null)).toBeNull()
    expect(parseEvoflowCuaDisplay({ kind: 'text', text: 'no marker here' })).toBeNull()
  })

  it('returns null for malformed marker JSON', () => {
    expect(parseEvoflowCuaDisplay(`body\n{evoflow-cua-display:{broken`)).toBeNull()
  })

  it('accepts object outputs carrying a text field', () => {
    const payload = { status: 'failed' }
    expect(parseEvoflowCuaDisplay({ text: `err\n${buildMarker(payload)}` })).toEqual(payload)
  })
})

describe('stripEvoflowCuaDisplayMarker', () => {
  it('removes only the marker line and keeps the body', () => {
    const output = `body line 1\nbody line 2\n\n${buildMarker({ status: 'success' })}`
    const stripped = stripEvoflowCuaDisplayMarker(output)
    expect(stripped).toBe('body line 1\nbody line 2')
    expect(stripped.includes(EVOFLOW_CUA_DISPLAY_PREFIX)).toBe(false)
  })

  it('leaves plain text untouched', () => {
    const text = 'no marker\nsecond line'
    expect(stripEvoflowCuaDisplayMarker(text)).toBe(text)
  })
})

describe('evoflowCuaAppKeyToIconRequest', () => {
  it('maps windows exe / aumid / darwin app keys to locator kinds', () => {
    expect(evoflowCuaAppKeyToIconRequest('windows-exe:d:\\app\\zcode\\zcode.exe')).toEqual({
      locators: [{ kind: 'windows-executable-path', value: 'd:\\app\\zcode\\zcode.exe' }],
    })
    expect(evoflowCuaAppKeyToIconRequest('windows-aumid:WeChat!App')).toEqual({
      locators: [{ kind: 'windows-aumid', value: 'WeChat!App' }],
    })
    expect(evoflowCuaAppKeyToIconRequest('darwin:com.apple.finder')).toEqual({
      locators: [{ kind: 'darwin-bundle-id', value: 'com.apple.finder' }],
    })
  })

  it('splits only at the first colon (drive letters stay intact)', () => {
    const request = evoflowCuaAppKeyToIconRequest('windows-exe:c:\\tools\\my app.exe')
    expect(request.locators[0].value).toBe('c:\\tools\\my app.exe')
  })

  it('returns null for unknown schemes or empty values', () => {
    expect(evoflowCuaAppKeyToIconRequest('linux-exe:/usr/bin/app')).toBeNull()
    expect(evoflowCuaAppKeyToIconRequest('windows-exe:')).toBeNull()
    expect(evoflowCuaAppKeyToIconRequest('')).toBeNull()
  })
})

describe('old-path tool result → CUA preview payload', () => {
  const cuaPayload = {
    status: 'success',
    images: [{ url: '/api/threads/t1/browser-snapshots/abc123', kb: 63 }],
    target_app: {
      app_key: 'windows-exe:d:\\app\\zcode\\zcode.exe',
      display_name: 'ZCode',
    },
  }

  it('carries the structured cua_display field through normalizeChatToolPayloadToEntries', () => {
    // sse_ui_normalize 解析标记后下发的 tool_result：正文已剥离标记 + 结构化字段。
    const payload = {
      name: 'mcp__node_repl__js',
      data: {
        type: 'tool',
        role: 'tool',
        name: 'mcp__node_repl__js',
        tool_call_id: 'call_cua_1',
        status: 'ok',
        content: 'app: ZCode pid=1\n[0] window ZCode (focused)\n\n[Screenshot captured: ok]',
        cua_display: cuaPayload,
      },
    }
    const entries = normalizeChatToolPayloadToEntries(payload)
    expect(entries).toHaveLength(1)
    expect(entries[0].name).toBe('mcp__node_repl__js')
    expect(entries[0].cua_display).toEqual(cuaPayload)
    expect(entries[0].output).not.toContain(EVOFLOW_CUA_DISPLAY_PREFIX)
  })

  it('falls back to parsing the marker from output text (history replay / un-upgraded stream)', () => {
    const payload = {
      name: 'mcp__node_repl__js',
      data: {
        type: 'tool',
        role: 'tool',
        name: 'mcp__node_repl__js',
        tool_call_id: 'call_cua_2',
        status: 'ok',
        content: `app: 微信 pid=2\n[0] window 微信\n\n${buildMarker(cuaPayload)}`,
      },
    }
    const entries = normalizeChatToolPayloadToEntries(payload)
    expect(entries).toHaveLength(1)
    const parsed = parseEvoflowCuaDisplay(entries[0].output)
    expect(parsed).toEqual(cuaPayload)
  })

  it('keeps non-CUA (browser / plain) tool outputs untouched', () => {
    const payload = {
      name: 'mcp__node_repl__js',
      data: {
        type: 'tool',
        role: 'tool',
        name: 'mcp__node_repl__js',
        tool_call_id: 'call_browser_1',
        status: 'ok',
        content: 'snapshot text\nno marker here',
      },
    }
    const entries = normalizeChatToolPayloadToEntries(payload)
    expect(entries[0].cua_display).toBeUndefined()
    expect(parseEvoflowCuaDisplay(entries[0].output)).toBeNull()
  })

  it('merges target_app from app: line when marker only has images', () => {
    const text = [
      'app: D:\\app\\Feishu\\Feishu.exe pid=42 "飞书"',
      '',
      '[Screenshot captured: /api/threads/t1/browser-snapshots/abc123def456 (12KB) — shown.]',
      '',
      buildMarker({
        status: 'success',
        images: [{ url: '/api/threads/t1/browser-snapshots/abc123def456', kb: 12 }],
      }),
    ].join('\n')
    const resolved = resolveEvoflowCuaDisplay(text)
    expect(resolved?.images?.[0]?.url).toContain('abc123def456')
    expect(resolved?.target_app?.display_name).toBe('飞书')
    expect(resolved?.target_app?.app_key).toContain('windows-exe:')
    expect(resolved?.target_app?.app_key.toLowerCase()).toContain('feishu.exe')
  })

  it('infers cua_display from Screenshot banner after marker was stripped', () => {
    const text = [
      'app: D:\\app\\Tencent\\WeChat\\Weixin.exe pid=13620 "微信"',
      'window: "微信" window_id=1',
      '',
      '[Screenshot captured: /api/threads/t1/browser-snapshots/9a3ac91947414d75 (363KB) — shown in the chat UI.]',
    ].join('\n')
    const inferred = inferEvoflowCuaDisplayFromOutput(text)
    expect(inferred?.images?.[0]?.url).toBe(
      '/api/threads/t1/browser-snapshots/9a3ac91947414d75',
    )
    expect(inferred?.target_app?.display_name).toBe('微信')
    expect(inferred?.target_app?.app_key).toContain('windows-exe:')
    expect(resolveEvoflowCuaDisplay(text)).toEqual(inferred)
  })

  it('keeps cua_display on the merged history tool after refresh', () => {
    const body = [
      '[Screenshot captured: /api/threads/t1/browser-snapshots/8a8b0e9695cb4753 (394KB) — shown in the chat UI.]',
      'app: D:\\app\\Tencent\\WeChat\\Weixin.exe pid=13620 "微信"',
    ].join('\n')
    const rows = messagesToDisplayRows([
      { role: 'user', content: '打开微信并截图' },
      {
        role: 'assistant',
        content: '好的',
        tool_calls: [
          {
            id: 'call_hist',
            name: 'mcp__node_repl__js',
            args: { title: '打开微信并截图', code: 'screenshot()' },
          },
        ],
      },
      {
        role: 'tool',
        type: 'tool',
        name: 'mcp__node_repl__js',
        tool_call_id: 'call_hist',
        content: body,
      },
    ])
    const assistant = rows.find((row) => row.role === 'assistant')
    const tool = (assistant?.tools || []).find((item) => item.id === 'call_hist')
    expect(tool?.cua_display?.target_app?.display_name).toBe('微信')
    expect(tool?.cua_display?.images?.[0]?.url).toContain('8a8b0e9695cb4753')
  })

  it('preserves cua_display when maybeSlimToolOutputForUi clears output', () => {
    const target = {
      name: 'mcp__node_repl__js',
      status: 'ok',
      output: [
        'app: D:\\app\\Tencent\\WeChat\\Weixin.exe pid=1 "微信"',
        '[Screenshot captured: /api/threads/t1/browser-snapshots/abc123def456 (12KB) — shown.]',
        '',
        buildMarker(cuaPayload),
      ].join('\n'),
    }
    maybeSlimToolOutputForUi(target)
    expect(target.output).toBe('')
    expect(target.output_truncated).toBe(true)
    expect(target.cua_display).toEqual(cuaPayload)
  })
})

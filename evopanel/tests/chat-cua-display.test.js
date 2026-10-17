import { describe, it, expect } from 'vitest'
import {
  parseEvoflowCuaDisplay,
  stripEvoflowCuaDisplayMarker,
  evoflowCuaAppKeyToIconRequest,
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

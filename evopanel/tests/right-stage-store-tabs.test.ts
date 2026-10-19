import { describe, expect, it, beforeEach } from 'vitest'
import { RightStageStore, hideRightStageIfKind, rightStageStore } from '../src/lib/right-stage/right-stage-store.js'
import { switchRightStageSession } from '../src/lib/right-stage/right-stage-session-memory.js'

describe('RightStageStore multi-tab', () => {
  beforeEach(() => {
    rightStageStore.hideAll()
  })

  it('closeTab only removes one tab', () => {
    const store = new RightStageStore()
    store.show({ kind: 'browser', id: 'primary', title: '浏览器' })
    store.show({ kind: 'workspace-browse', id: 'primary', title: '工作区文件' })
    expect(store.getSnapshot().tabs.map((t) => t.kind)).toEqual(['browser', 'workspace-browse'])
    store.closeTab('browser:primary')
    const snap = store.getSnapshot()
    expect(snap.tabs.map((t) => `${t.kind}:${t.id}`)).toEqual(['workspace-browse:primary'])
    expect(snap.surface?.kind).toBe('workspace-browse')
  })

  it('collapse keeps tabs; hideAll clears and folds', () => {
    const store = new RightStageStore()
    store.show({ kind: 'browser', id: 'primary' })
    expect(store.getSnapshot().collapsed).toBe(false)
    store.collapse()
    expect(store.getSnapshot().collapsed).toBe(true)
    expect(store.getSnapshot().tabs).toHaveLength(1)
    store.expand()
    expect(store.getSnapshot().collapsed).toBe(false)
    store.hideAll()
    const snap = store.getSnapshot()
    expect(snap.tabs).toEqual([])
    expect(snap.collapsed).toBe(true)
    expect(snap.recentClosed.some((e) => e.key === 'browser:primary')).toBe(true)
  })

  it('hideRightStageIfKind does not wipe unrelated tabs', () => {
    rightStageStore.show({ kind: 'browser', id: 'primary' })
    rightStageStore.show({ kind: 'workspace-browse', id: 'primary' })
    hideRightStageIfKind('workspace-browse')
    const snap = rightStageStore.getSnapshot()
    expect(snap.tabs.map((t) => t.kind)).toEqual(['browser'])
    expect(snap.surface?.kind).toBe('browser')
  })

  it('rejects artifacts kind', () => {
    const store = new RightStageStore()
    store.show({ kind: 'artifacts', id: 'primary' })
    expect(store.getSnapshot().tabs).toEqual([])
  })

  it('session switch restores tabs cache', () => {
    rightStageStore.show({ kind: 'browser', id: 'primary' })
    switchRightStageSession('sess-a', 'sess-b')
    expect(rightStageStore.getSnapshot().tabs).toEqual([])
    rightStageStore.show({ kind: 'workspace-browse', id: 'primary' })
    switchRightStageSession('sess-b', 'sess-a')
    const snap = rightStageStore.getSnapshot()
    expect(snap.tabs.map((t) => t.kind)).toEqual(['browser'])
    expect(snap.collapsed).toBe(false)
  })
})

import { rightStageStore } from './right-stage-store.js'

/** 打开或激活摘要（Info Rail）标签，不关掉其它页。 */
export function ensureSummaryStage(opts?: { sessionKey?: string }) {
  const sessionKey = String(opts?.sessionKey || '').trim() || undefined
  rightStageStore.show({
    kind: 'summary',
    id: 'primary',
    title: '摘要',
    layout: 'narrow',
    sessionKey,
    data: {},
  })
}

export function closeSummaryStage() {
  rightStageStore.closeTab('summary:primary')
}

export function hasSummaryStage(): boolean {
  return rightStageStore
    .getSnapshot()
    .tabs.some((t) => String(t.kind || '') === 'summary')
}

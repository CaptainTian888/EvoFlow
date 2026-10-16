import { rightStageStore } from './right-stage-store.js'

export type EnsureTerminalStageInput = {
  toolCallId: string
  title?: string
  command?: string
  outputFallback?: string
  sessionKey?: string
  running?: boolean
}

/** 打开或激活终端标签（同 toolCallId 只激活，不另开）。 */
export function ensureTerminalStage(input: EnsureTerminalStageInput) {
  const toolCallId = String(input.toolCallId || '').trim()
  if (!toolCallId) return
  const sessionKey = String(input.sessionKey || '').trim() || undefined
  rightStageStore.show({
    kind: 'terminal',
    id: toolCallId,
    title: String(input.title || '').trim() || '终端',
    layout: 'half',
    sessionKey,
    data: {
      toolCallId,
      command: String(input.command || ''),
      outputFallback: String(input.outputFallback || ''),
      sessionKey: sessionKey || '',
      running: !!input.running,
    },
  })
}

export function closeTerminalStage(toolCallId: string) {
  const id = String(toolCallId || '').trim()
  if (!id) return
  rightStageStore.closeTab(`terminal:${id}`)
}

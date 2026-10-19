import type { BackgroundWorkStreamItem } from '../chat-types.js'

export function mergeBackgroundWorkEvent(
  map: Record<string, BackgroundWorkStreamItem>,
  ev: Record<string, unknown>,
): void {
  const workId = String(ev.workId || ev.work_id || '').trim()
  if (!workId) return
  const prev = map[workId]
  const startedAt = Number(ev.startedAt ?? ev.started_at ?? prev?.startedAt ?? Date.now())
  const status = String(ev.status || prev?.status || 'running')
  const row: BackgroundWorkStreamItem = {
    workId,
    kind: 'bash',
    title: String(ev.title || prev?.title || ev.command || workId).trim() || workId,
    status,
    startedAt: Number.isFinite(startedAt) ? startedAt : Date.now(),
    cancellable: status === 'running' ? ev.cancellable !== false : false,
    toolCallId: String(ev.toolCallId || ev.tool_call_id || prev?.toolCallId || workId).trim(),
    command: String(ev.command || prev?.command || '').trim() || undefined,
  }
  if (status !== 'running') {
    row.endedAt = Date.now()
  }
  map[workId] = row
}

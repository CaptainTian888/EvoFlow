import { gatewayFetch } from '../../lib/gateway-json.js'

export type BackgroundBashWork = {
  workId: string
  kind: 'bash'
  title: string
  status: string
  startedAt: number
  endedAt?: number | null
  cancellable?: boolean
  toolCallId?: string
  command?: string
  outputPath?: string
  exitCode?: number | null
}

export async function listBackgroundBashWorks(opts?: {
  runningOnly?: boolean
  threadId?: string
}): Promise<BackgroundBashWork[]> {
  const q = new URLSearchParams()
  q.set('running_only', opts?.runningOnly === false ? 'false' : 'true')
  if (opts?.threadId) q.set('thread_id', opts.threadId)
  const res = await gatewayFetch(`/api/background-bash?${q.toString()}`)
  if (!res.ok) throw new Error(`background-bash list failed: ${res.status}`)
  const data = await res.json()
  const works = Array.isArray(data?.works) ? data.works : []
  return works as BackgroundBashWork[]
}

export async function fetchBackgroundBashOutput(workId: string): Promise<{
  kind: string
  workId: string
  status?: string
  output?: string
  truncated?: boolean
  outputPath?: string
}> {
  const res = await gatewayFetch(`/api/background-bash/${encodeURIComponent(workId)}/output`)
  if (!res.ok) throw new Error(`background-bash output failed: ${res.status}`)
  return res.json()
}

export async function stopBackgroundBashWork(workId: string): Promise<void> {
  const res = await gatewayFetch(`/api/background-bash/${encodeURIComponent(workId)}/stop`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`background-bash stop failed: ${res.status}`)
}

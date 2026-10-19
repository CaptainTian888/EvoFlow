import type { RightStageSurface } from './right-stage-types.js'

/** 无 sessionKey 的旧标签对所有会话可见；有归属则只在匹配会话显示。 */
export function isRightStageTabVisibleForSession(
  tab: RightStageSurface,
  sessionKey: string | null | undefined,
): boolean {
  const tabSk = String(tab.sessionKey || '').trim()
  if (!tabSk) return true
  const sk = String(sessionKey || '').trim()
  if (!sk) return true
  return tabSk === sk
}

export function filterRightStageTabsForSession(
  tabs: RightStageSurface[],
  sessionKey: string | null | undefined,
): RightStageSurface[] {
  return (tabs || []).filter((t) => isRightStageTabVisibleForSession(t, sessionKey))
}

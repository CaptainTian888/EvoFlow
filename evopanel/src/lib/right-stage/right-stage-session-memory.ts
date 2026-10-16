/**
 * 右栏按会话缓存：切会话时整表换出 / 换回，标签实例语义对齐「浏览器标签页」。
 * 不落盘 localStorage——进程内 Map，最多保留最近 N 个会话。
 */
import {
  rightStageStore,
  type RightStageSessionMemory,
} from './right-stage-store.js'

const MAX_ENTRIES = 40

const sessionMemory = new Map<string, RightStageSessionMemory>()

function touch(key: string, memory: RightStageSessionMemory) {
  sessionMemory.delete(key)
  sessionMemory.set(key, memory)
  while (sessionMemory.size > MAX_ENTRIES) {
    const oldest = sessionMemory.keys().next().value
    if (oldest == null) break
    sessionMemory.delete(oldest)
  }
}

export function saveRightStageSessionMemory(sessionKey: string | null | undefined) {
  const key = String(sessionKey || '').trim()
  if (!key) return
  touch(key, rightStageStore.exportSessionMemory())
}

export function restoreRightStageSessionMemory(sessionKey: string | null | undefined) {
  const key = String(sessionKey || '').trim()
  if (!key) {
    rightStageStore.importSessionMemory(null)
    return
  }
  rightStageStore.importSessionMemory(sessionMemory.get(key) ?? null)
}

/**
 * 从 fromKey 切到 toKey：先冻结当前侧栏，再换入目标会话记忆。
 * 同 key 时只同步写回缓存，不重置 UI。
 */
export function switchRightStageSession(
  fromKey: string | null | undefined,
  toKey: string | null | undefined,
) {
  const from = String(fromKey || '').trim()
  const to = String(toKey || '').trim()
  if (from && from === to) {
    saveRightStageSessionMemory(from)
    return
  }
  if (from) saveRightStageSessionMemory(from)
  // 换入目标会话的标签缓存后，browser-embed-surface 根据激活页决定显示或隐藏。
  restoreRightStageSessionMemory(to || null)
}

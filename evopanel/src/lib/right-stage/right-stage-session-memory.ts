/**
 * 右栏按会话缓存：切会话时整表换出 / 换回，标签实例语义对齐「浏览器标签页」。
 * 不落盘 localStorage——进程内 Map，最多保留最近 N 个会话。
 */
import { browserEmbedPark } from '../browser-embed-client.js'
import { NODE_REPL_BRIDGE_THREAD_ID } from '../browser-panel-store.js'
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
  // 切会话立刻停靠原生浏览器：目标会话可能没有浏览器标签，或激活的是通报/其它页。
  // 等 React 卸载再 park 会晚一帧，HWND 会闪在新会话上。
  void browserEmbedPark(NODE_REPL_BRIDGE_THREAD_ID)
  restoreRightStageSessionMemory(to || null)
}

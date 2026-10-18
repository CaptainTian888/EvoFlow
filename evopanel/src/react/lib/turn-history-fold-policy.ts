/**
 * 「已工作」默认折叠策略。
 *
 * - 更早的回合：结束后默认折叠。
 * - 整段对话的最后一轮：只有「单一正文」或「一段思考 + 正文」才折叠。
 *   还在调工具、或过程里有工具 / 多段工作，保持展开。
 */
import type { AssistantBubbleSlot } from './message-row-display-plan.js'

export function shouldDefaultOpenTurnHistory(opts: {
  isStreaming: boolean
  threadBusy: boolean
  interactiveToolApproval: boolean
  approvalLatch: boolean
  /** 当前会话里最后一条助手回合（不含更早的历史回合） */
  isLatestTurn: boolean
  /** 最后一轮里仍有 running / in_progress 的工具 */
  toolsRunning: boolean
  slots: AssistantBubbleSlot[]
}): boolean {
  if (
    opts.isStreaming ||
    opts.threadBusy ||
    opts.interactiveToolApproval ||
    opts.approvalLatch
  ) {
    return true
  }
  if (!opts.isLatestTurn) return false
  if (opts.toolsRunning) return true
  return !isSimpleBodyOrThinkingPlusBody(opts.slots)
}

/** 单一正文，或恰好一段思考加一段正文。出现工具或多段正文则不是。 */
export function isSimpleBodyOrThinkingPlusBody(slots: AssistantBubbleSlot[]): boolean {
  let reasoning = 0
  let body = 0
  for (const slot of slots) {
    if (slot.kind === 'thinking-wait') continue
    if (slot.kind === 'top-reasoning' || slot.kind === 'reasoning-pending') {
      reasoning += 1
      continue
    }
    if (slot.kind === 'plain-body' || slot.kind === 'live-tail' || slot.kind === 'legacy-body') {
      body += 1
      continue
    }
    if (slot.kind === 'chunk') {
      const chunk = slot.chunk
      if (chunk.kind === 'text') {
        body += 1
        continue
      }
      if (chunk.kind === 'activity') {
        for (const piece of chunk.pieces) {
          if (piece.kind === 'reasoning') reasoning += 1
          else if (piece.kind === 'text') body += 1
          else return false
        }
        continue
      }
      return false
    }
    return false
  }
  return body === 1 && reasoning <= 1
}

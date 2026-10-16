/**
 * 任务通知提示音（气泡声）：系统通知展示后异步播放的自定 pop 音效。
 * 机制移植自 ZCode：系统通知本身静音，由 webview 用 Audio 播自定音效；
 * 声音是通知的子能力（关闭系统通知后不再响），开关判定收口在播放入口，
 * 保证所有调用方行为一致。播放失败按增强体验静默处理，不打断通知主链路。
 */
import popSoundUrl from '../assets/sounds/task-notification-pop.mp3'

const LS_SOUND_ENABLED = 'evopanel_task_notify_sound_enabled'

/** @type {HTMLAudioElement | null} */
let popAudio = null

export function isTaskNotificationSoundEnabled() {
  try {
    const v = localStorage.getItem(LS_SOUND_ENABLED)
    if (v === '0' || v === 'false') return false
  } catch {
    /* ignore */
  }
  return true
}

export function setTaskNotificationSoundEnabled(on) {
  try {
    localStorage.setItem(LS_SOUND_ENABLED, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export async function playTaskNotificationSound() {
  if (!isTaskNotificationSoundEnabled()) return
  if (typeof Audio === 'undefined') return
  if (!popAudio) {
    popAudio = new Audio(popSoundUrl)
    popAudio.preload = 'auto'
  }
  try {
    // 同一 Audio 实例在连续通知里复用时，若停在结束态，下一轮会直接静默；
    // 显式回到起点再播，并吞掉自动播放策略等异常。
    popAudio.pause()
    popAudio.currentTime = 0
    await popAudio.play()
  } catch {
    /* ignore */
  }
}

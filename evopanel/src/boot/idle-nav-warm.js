/**
 * Boot 完成后的空闲预热：把高频菜单页模块 chunk 提前拉进 _moduleCache。
 *
 * 背景：路由模块是首次点击才动态 import（_moduleCache 未命中即冷加载），
 * 侧栏 hover 预热覆盖不到键盘/快速点击路径。boot 完成后 requestIdleCallback
 * 逐个 warm，用户之后首次点击各菜单页免等模块加载。
 *
 * 只 warm 模块（不预取数据）：数据有 TTL 与时新鲜度问题，交给 nav-panel-prefetch
 * 的 hover 路径继续负责。串行 + idle 调度，避免抢占首屏带宽。
 */
import { prefetchRoute } from '../router.js'

/** 高频菜单：任务 / 应用 / 智能体员工 / 知识库 / 资产中心 / 自动化 */
const IDLE_WARM_ROUTES = [
  '/tasks',
  '/apps',
  '/proactive',
  '/knowledge',
  '/assets',
  '/cron',
]

let _warmed = false

export function warmFrequentMenuModules() {
  if (_warmed) return
  _warmed = true
  const idle =
    typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function'
      ? window.requestIdleCallback.bind(window)
      : (fn) => setTimeout(fn, 1200)

  idle(() => {
    for (const path of IDLE_WARM_ROUTES) {
      // prefetchRoute 内部命中 _moduleCache 会直接返回；串行触发即可，
      // 浏览器端 import() 本身有模块级去重，不会重复下载。
      void prefetchRoute(path).catch(() => {})
    }
  })
}

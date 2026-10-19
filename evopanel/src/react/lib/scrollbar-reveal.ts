/**
 * macOS overlay 风格滚动条显隐：滚动条平时由 CSS 设为透明（布局占位不变），
 * 这里只负责在「鼠标靠近容器右缘」或「容器发生滚动」时给根元素挂上 showClass、
 * 静默约 1s 后移除，配合 CSS 让 thumb 短暂显现。不触碰滚动行为本身。
 */
export function attachScrollbarReveal(
  el: HTMLElement,
  showClass: string,
  opts: { edgePx?: number; showMs?: number } = {},
): () => void {
  const edgePx = opts.edgePx ?? 28
  const showMs = opts.showMs ?? 1000
  let hideTimer = 0
  const show = () => {
    el.classList.add(showClass)
    window.clearTimeout(hideTimer)
    hideTimer = window.setTimeout(() => el.classList.remove(showClass), showMs)
  }
  // 内部滚动容器的 scroll 不冒泡，挂捕获阶段才能一并收到
  const onScroll = () => show()
  const onMouseMove = (e: MouseEvent) => {
    if (el.getBoundingClientRect().right - e.clientX <= edgePx) show()
  }
  el.addEventListener('scroll', onScroll, { capture: true, passive: true })
  el.addEventListener('mousemove', onMouseMove, { passive: true })
  return () => {
    el.removeEventListener('scroll', onScroll, { capture: true })
    el.removeEventListener('mousemove', onMouseMove)
    window.clearTimeout(hideTimer)
    el.classList.remove(showClass)
  }
}

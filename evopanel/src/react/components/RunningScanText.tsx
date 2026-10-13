/** 运行中逐字扫光（工具行 / 思考行共用）；周期随字数变化，避免多波叠扫 */
export function RunningScanText({
  text,
  className,
  maxChars = 72,
}: {
  text: string
  className?: string
  maxChars?: number
}) {
  const raw = String(text || '')
  if (!raw) return null
  const chars = Array.from(raw)
  const head = chars.slice(0, Math.max(1, maxChars))
  const tail = chars.length > head.length ? chars.slice(head.length).join('') : ''
  const n = head.length
  const stepSec = 0.048
  // 量化到 0.5s 档位：流式期间字符数每 delta 增长，连续变化的 animation-duration
  // 会让 CSS 动画反复重算（扫光跳变/闪烁）；档位化后 --scan-dur 仅偶尔变化。
  const durationSec = Math.max(2, Math.ceil((n * stepSec + 0.9) / 0.5) * 0.5)
  return (
    <span
      className={className ? `tool-running-scan ${className}` : 'tool-running-scan'}
      style={{
        ['--scan-dur' as string]: `${durationSec}s`,
        ['--scan-step' as string]: `${stepSec}s`,
      }}
    >
      {head.map((ch, i) => (
        <span key={i} className="tool-char-scan" style={{ ['--i' as string]: i }}>
          {ch === ' ' ? '\u00a0' : ch}
        </span>
      ))}
      {tail}
    </span>
  )
}

/** Parse `#file` / `@employee` / `/skill-or-plugin` mention at cursor.
 *
 * Trigger chars:
 * - `#` -> file mention (workspace file autocomplete)
 * - `@` -> employee mention (dispatch task to an Agent Workforce role)
 * - `/` -> capability mention (skill or plugin search, EvoFlow custom)
 */
export type MentionType = 'file' | 'employee' | 'skill' | 'plugin'

export type MentionRange = {
  type: MentionType
  query: string
  start: number
  end: number
}

/** Match the trigger char + query at the cursor position.
 *
 * The trigger must be preceded by start-of-text or whitespace / bracket so that
 * emails (`foo@bar`) are not mistaken for employee mentions.
 */
function matchTrigger(text: string, cursor: number, trigger: string): MentionRange | null {
  const before = text.slice(0, Math.max(0, cursor))
  // Escape trigger for regex (both `#` and `@` are safe but be defensive)
  const t = trigger.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp(`(?:^|[\\s([{,'"\`])${t}([^\\s${t}]*)$`)
  const match = before.match(re)
  if (!match) return null
  const query = match[1] ?? ''
  const start = before.length - match[0].length
  const end = cursor
  const typeMap: Record<string, MentionType> = {
    '#': 'file',
    '@': 'employee',
    '/': 'skill-or-plugin' as MentionType,
  }
  return { type: typeMap[trigger] ?? trigger as MentionType, query, start, end }
}

export function getMentionAtCursor(text: string, cursor: number): MentionRange | null {
  // `/` takes priority — slash commands are more specific than @ or #.
  const slash = matchTrigger(text, cursor, '/')
  if (slash) return slash
  // Employee (`@`) takes precedence only when the char right before the query is
  // actually `@`; otherwise fall back to file (`#`). Both can coexist because
  // the preceding-trigger check disambiguates them.
  const emp = matchTrigger(text, cursor, '@')
  if (emp) return emp
  return matchTrigger(text, cursor, '#')
}

/** File-only mention (kept for call sites that explicitly want `#file`). */
export function getFileMentionAtCursor(text: string, cursor: number): MentionRange | null {
  return matchTrigger(text, cursor, '#')
}

/** Employee-only mention (`@员工`). */
export function getEmployeeMentionAtCursor(text: string, cursor: number): MentionRange | null {
  return matchTrigger(text, cursor, '@')
}

export function basenameFromPath(p: string): string {
  const s = String(p || '').replace(/\\/g, '/')
  const parts = s.split('/').filter(Boolean)
  return parts[parts.length - 1] || s
}

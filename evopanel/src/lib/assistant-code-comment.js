/**
 * 助手正文中的行内代码评论（`::code-comment{...}`）提取与投影。
 *
 * 与 `<artifact_display>` 提示词块成对：提示词教模型按协议输出指令，本文件把指令
 * 从正文里投影成结构化评论 + 可渲染卡片，并保证：
 * - 协议原文不出现在用户可见正文里（整行则删行，否则原位留白）；
 * - 模型常把提示词示例连反引号/围栏一起抄进正文：纯协议包装先解包再投影
 *   （与 `@@path@@` 反引号解包同理）；夹杂其它代码的示例区间仍不解析；
 * - 流式未闭合的半截指令 / 协议名前缀尾巴先隐藏，闭合后再转正。
 */

import {
  extractAssistantDirectives,
  findAssistantDirectivePrefixStart,
  findMarkdownCodeRanges,
  findUnclosedAssistantDirectiveStart,
  overlapsAssistantTextRanges,
} from './assistant-directive-parser.js'
import { cleanHostPath, isAbsoluteHostPath } from './workspace-abs-path.js'

/** @typedef {0 | 1 | 2 | 3} AssistantCodeCommentPriority */

/**
 * @typedef {Object} AssistantCodeComment
 * @property {string} title
 * @property {string} body
 * @property {string} file
 * @property {number} [startLine]
 * @property {number} [endLine]
 * @property {AssistantCodeCommentPriority} [priority]
 * @property {number} sourceStart
 * @property {number} sourceEnd
 */

/**
 * @typedef {AssistantCodeComment & { id: string, path: string, displayPath: string }} AssistantCodeCommentCard
 */

/**
 * @typedef {Object} AssistantCodeCommentProjection
 * @property {AssistantCodeComment[]} comments
 * @property {string} visibleText
 */

const CODE_COMMENT_DIRECTIVE_NAME = 'code-comment'

/** code-comment 的宽容面：允许反引号包值（模型常把路径包进行内反引号）；中文模型偶发智能引号。 */
const CODE_COMMENT_SYNTAX_OPTIONS = { allowBacktickQuotes: true, allowSmartQuotes: true }

/** @param {string | undefined} value */
function parsePositiveInteger(value) {
  if (!value || !/^\d+$/.test(value)) return undefined
  const parsed = Number.parseInt(value, 10)
  return parsed > 0 ? parsed : undefined
}

/** @param {string | undefined} value */
function parsePriority(value) {
  if (!value || !/^[0-3]$/.test(value)) return undefined
  return Number.parseInt(value, 10)
}

/**
 * 内文是否「只含」可投影的 code-comment 指令（可多条，中间仅空白）。
 * 用于识别模型把提示词示例连反引号/围栏一起抄进正文的情况。
 * @param {string} inner
 */
function isProtocolOnlyCodeCommentInner(inner) {
  const trimmed = String(inner || '').trim()
  if (!trimmed) return false
  const directives = extractAssistantDirectives(
    trimmed,
    CODE_COMMENT_DIRECTIVE_NAME,
    CODE_COMMENT_SYNTAX_OPTIONS,
  )
  if (directives.length === 0) return false
  let cursor = 0
  for (const directive of directives) {
    if (trimmed.slice(cursor, directive.start).trim()) return false
    const title = directive.parameters?.title?.trim()
    const body = directive.parameters?.body?.trim()
    const file = directive.parameters?.file?.trim()
    if (!directive.parameters || !title || !body || !file) return false
    cursor = directive.end
  }
  return !trimmed.slice(cursor).trim()
}

/**
 * 剥掉纯协议包装的行内反引号或围栏，露出可投影的 `::code-comment{...}`。
 * 夹杂其它代码的示例区间原样保留（仍走 protectedRanges 跳过）。
 * @param {string} content
 */
function unwrapProtocolCodeCommentWrappers(content) {
  const source = String(content || '')
  if (!source.includes(CODE_COMMENT_DIRECTIVE_NAME)) return source

  const ranges = findMarkdownCodeRanges(source)
  if (ranges.length === 0) return source

  let result = source
  for (const [start, end] of [...ranges].sort((left, right) => right[0] - left[0])) {
    const slice = result.slice(start, end)
    let inner = null

    // 围栏 range 常以闭合行后的 \n 结尾，故闭合标记后允许可选换行。
    const fence = /^ {0,3}(`{3,}|~{3,})[^\n]*\n([\s\S]*?)\n {0,3}\1[ \t]*\n?$/.exec(slice)
    if (fence) {
      inner = fence[2]
    } else {
      const inlineMatch = /^(`+)([\s\S]*?)\1$/.exec(slice)
      if (inlineMatch && !slice.includes('\n')) {
        inner = inlineMatch[2]
      }
    }

    if (inner == null || !isProtocolOnlyCodeCommentInner(inner)) continue
    result = result.slice(0, start) + String(inner).trim() + result.slice(end)
  }
  return result
}

/**
 * @param {string} content
 * @returns {AssistantCodeComment[]}
 */
function extractAssistantCodeComments(content) {
  const protectedRanges = findMarkdownCodeRanges(content)
  return extractAssistantDirectives(
    content,
    CODE_COMMENT_DIRECTIVE_NAME,
    CODE_COMMENT_SYNTAX_OPTIONS,
  ).flatMap((directive) => {
    if (
      !directive.parameters ||
      overlapsAssistantTextRanges(directive.start, directive.start + 1, protectedRanges)
    ) {
      return []
    }

    const title = directive.parameters.title?.trim()
    const body = directive.parameters.body?.trim()
    const file = directive.parameters.file?.trim()
    if (!title || !body || !file) return []

    const startLine = parsePositiveInteger(directive.parameters.start)
    const parsedEndLine = parsePositiveInteger(directive.parameters.end)
    const hasValidRange =
      startLine !== undefined && (parsedEndLine === undefined || parsedEndLine >= startLine)
    const priority = parsePriority(directive.parameters.priority)

    return [
      {
        title,
        body,
        file,
        sourceStart: directive.start,
        sourceEnd: directive.end,
        ...(hasValidRange
          ? {
              startLine,
              endLine: parsedEndLine ?? startLine,
            }
          : {}),
        ...(priority !== undefined ? { priority } : {}),
      },
    ]
  })
}

/**
 * 整行独占的指令删整行；行内夹杂的指令原位替换成单个空格，保住两侧 Markdown。
 * @param {string} content
 * @param {AssistantCodeComment} comment
 * @returns {{ start: number, end: number, replacement: string }}
 */
function replacementForComment(content, comment) {
  const lineStart = content.lastIndexOf('\n', comment.sourceStart - 1) + 1
  const nextNewline = content.indexOf('\n', comment.sourceEnd)
  const lineEnd = nextNewline < 0 ? content.length : nextNewline
  const prefix = content.slice(lineStart, comment.sourceStart)
  const suffix = content.slice(comment.sourceEnd, lineEnd)
  if (!prefix.trim() && !suffix.trim()) {
    return {
      start: lineStart,
      end: nextNewline < 0 ? lineEnd : nextNewline + 1,
      replacement: '',
    }
  }
  return {
    start: comment.sourceStart,
    end: comment.sourceEnd,
    replacement: ' ',
  }
}

/**
 * @param {string} content
 * @param {{ streaming?: boolean }} [options]
 * @returns {AssistantCodeCommentProjection}
 */
export function projectAssistantCodeComments(content, options = {}) {
  // 先解包「整段只有协议」的反引号/围栏，再提取；否则历史里抄自提示词示例的
  // `::code-comment{...}` 会被当成代码示例跳过，正文仍显示协议原文。
  const source = unwrapProtocolCodeCommentWrappers(String(content || ''))
  const comments = extractAssistantCodeComments(source)
  const replacements = comments.map((comment) => replacementForComment(source, comment))

  if (options.streaming) {
    const protectedRanges = findMarkdownCodeRanges(source)
    const unclosedStart = findUnclosedAssistantDirectiveStart(
      source,
      CODE_COMMENT_DIRECTIVE_NAME,
      protectedRanges,
      CODE_COMMENT_SYNTAX_OPTIONS,
    )
    if (unclosedStart !== null) {
      // 流式尾部直接交给 Markdown 会在闭合前把协议原文闪给用户。
      replacements.push({ start: unclosedStart, end: source.length, replacement: '' })
    } else {
      const prefixStart = findAssistantDirectivePrefixStart(
        source,
        [CODE_COMMENT_DIRECTIVE_NAME],
        protectedRanges,
      )
      if (prefixStart !== null) {
        replacements.push({ start: prefixStart, end: source.length, replacement: '' })
      }
    }
  }

  let visibleText = source
  for (const replacement of replacements.sort((left, right) => right.start - left.start)) {
    visibleText =
      visibleText.slice(0, replacement.start) +
      replacement.replacement +
      visibleText.slice(replacement.end)
  }

  return { comments, visibleText }
}

/** @param {string} path */
function normalizeDisplayPath(path) {
  return String(path || '')
    .replace(/\\/g, '/')
    .replace(/\/+$/, '')
}

/** @param {string} path */
function isWindowsPath(path) {
  return /^[a-zA-Z]:[\\/]/.test(path) || path.startsWith('\\\\')
}

/**
 * 工作区内路径转显示用相对路径；工作区外保留归一化后的完整路径。
 * @param {string} workspaceRoot
 * @param {string} path
 */
function displayPathForWorkspace(workspaceRoot, path) {
  const normalizedRoot = normalizeDisplayPath(workspaceRoot)
  const normalizedPath = normalizeDisplayPath(path)
  if (!normalizedRoot) return normalizedPath
  const windows = isWindowsPath(normalizedRoot)
  const comparedRoot = windows ? normalizedRoot.toLowerCase() : normalizedRoot
  const comparedPath = windows ? normalizedPath.toLowerCase() : normalizedPath
  if (!comparedPath.startsWith(`${comparedRoot}/`)) return normalizedPath
  return normalizedPath.slice(normalizedRoot.length + 1)
}

/**
 * 评论里的 file 参数 → 可打开的路径：绝对路径原样；相对路径基于工作区根拼接。
 * @param {string | undefined} workspaceRoot
 * @param {string} rawFile
 */
function resolveCommentFilePath(workspaceRoot, rawFile) {
  const cleaned = cleanHostPath(rawFile)
  if (!cleaned) return ''
  if (isAbsoluteHostPath(cleaned)) return cleaned
  const root = String(workspaceRoot || '').trim()
  if (!root) return cleaned
  const sep = root.includes('\\') ? '\\' : '/'
  const relative = cleaned.replace(/^[/\\]+/, '').replace(/\//g, sep)
  return `${root.replace(/[/\\]+$/, '')}${sep}${relative}`
}

/** @param {string} path */
function basenameFromPath(path) {
  const parts = normalizeDisplayPath(path).split('/').filter(Boolean)
  return parts[parts.length - 1] || path
}

/**
 * 结构化评论 → 可渲染卡片（路径解析失败或不在工作区内的丢弃），供 UI 层消费。
 * @param {AssistantCodeComment[]} comments
 * @param {string | undefined} workspaceRoot
 * @param {number} [limit]
 * @returns {AssistantCodeCommentCard[]}
 */
export function buildAssistantCodeCommentCards(comments, workspaceRoot, limit = 50) {
  const root = String(workspaceRoot || '').trim()
  /** @type {AssistantCodeCommentCard[]} */
  const cards = []
  for (const comment of comments) {
    const path = resolveCommentFilePath(root, comment.file)
    if (!path) continue
    cards.push({
      ...comment,
      id: `code-comment:${comment.sourceStart}:${path}`,
      path,
      displayPath: displayPathForWorkspace(root, path) || basenameFromPath(path),
    })
    if (cards.length >= limit) break
  }
  return cards
}

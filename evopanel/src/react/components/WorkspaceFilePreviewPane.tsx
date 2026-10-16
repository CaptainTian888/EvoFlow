import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { formatWorkspacePathForDisplay } from '../../lib/workspace-api-scope.js'
import {
  isWorkspaceAudioPath,
  isWorkspaceImagePath,
  isWorkspaceMediaBinaryPath,
  isWorkspaceVideoPath,
  resolveWorkspaceRelMediaSrc,
} from '../../lib/chat-image-src.js'
import { showChatLightbox } from '../../lib/chat-lightbox.js'
import {
  getBinaryFilePreviewHint,
  isStreamWriteContentDisplayable,
} from '../../lib/workspace-preview-path.js'
import { prepareHtmlSrcDocForPreview } from '../../lib/workspace-html-preview.js'
import { useThrottledValue } from '../hooks/useThrottledValue.js'
import { isStreamThrottleEnabled } from '../lib/stream-throttle-toggle.js'
import {
  isMarkdownDocumentPath,
  MarkdownDocumentView,
} from './MarkdownDocumentView.js'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover.js'

export type WorkspacePreviewState = {
  path: string
  name: string
  loading: boolean
  content: string
  error: string | null
  binary: boolean
  truncated: boolean
  size: number | null
  /** 图片/视频/音频：直接 serve-file 预览，不走文本读取 */
  mediaSrc?: string | null
  mediaKind?: 'image' | 'video' | 'audio' | null
  /** 工具参数流式生成中（未落盘） */
  streaming?: boolean
}

type PreviewZoomControls = {
  percent: number
  onZoomOut: () => void
  onZoomIn: () => void
  onReset: () => void
  canZoomOut: boolean
  canZoomIn: boolean
  canReset: boolean
}

type MarkdownViewMode = 'preview' | 'code'

type Props = {
  preview: WorkspacePreviewState | null
  onClose?: () => void
  compact?: boolean
  /** 嵌在右栏时：无页内 × / 无缩放条，关闭走标签条。 */
  embedded?: boolean
  /** 弹窗内正文缩放（0.75–2，默认 1） */
  contentZoom?: number
  workspaceRoot?: string
  threadId?: string
  /** 仅弹窗模式：缩放控件 */
  zoomControls?: PreviewZoomControls | null
  /**
   * Markdown：是否允许编辑源码（与 ZCode 的「原文」查看分开；原文用 markdownViewMode=code）。
   */
  allowMarkdownEdit?: boolean
  /** Markdown 编辑时回调（需配合 allowMarkdownEdit）。 */
  onMarkdownChange?: (text: string) => void
  /** 读取失败时重试。 */
  onRetry?: () => void
  /** 代码评论定位：打开后滚动并高亮该 1-based 行（endLine 缺省等于 startLine）。 */
  focusLine?: number
  focusEndLine?: number
  /** 代码评论批注：渲染在目标行区间下方（标题/正文/优先级）。 */
  focusAnnotation?: WorkspaceFocusAnnotation
}

/** 代码评论批注：定位行的区间下方渲染标题/正文/优先级。 */
export type WorkspaceFocusAnnotation = {
  title?: string
  body?: string
  priority?: number
}

/** 行号渲染上限：超过则只渲染目标行附近窗口，避免大文件整棵 DOM。 */
const FOCUSED_CODE_MAX_LINES = 3000
const FOCUSED_CODE_WINDOW = 400

/**
 * 行号版代码块（仅代码评论定位路径使用）：目标行区间高亮、滚动到位，
 * 区间末行下方渲染评论批注块。普通预览仍走原 <pre><code>，外观不变。
 */
function FocusedCodeBlock({
  content,
  focusLine,
  focusEndLine,
  annotation,
}: {
  content: string
  focusLine: number
  focusEndLine?: number
  annotation?: WorkspaceFocusAnnotation
}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const lines = useMemo(() => String(content || '').split('\n'), [content])
  const windowed = lines.length > FOCUSED_CODE_MAX_LINES
  const sliceStart = windowed ? Math.max(0, focusLine - 1 - FOCUSED_CODE_WINDOW / 2) : 0
  const sliceEnd = windowed ? Math.min(lines.length, sliceStart + FOCUSED_CODE_WINDOW) : lines.length
  const rendered = lines.slice(sliceStart, sliceEnd)
  const endLine = Math.max(focusLine, Number(focusEndLine) || focusLine)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    // 内容挂载后下一帧再定位，避免容器尚未布局时 scrollIntoView 落空
    const raf = requestAnimationFrame(() => {
      const target = host.querySelector<HTMLElement>(`[data-line="${focusLine}"]`)
      target?.scrollIntoView({ block: 'center' })
    })
    return () => cancelAnimationFrame(raf)
  }, [focusLine, content])

  return (
    <div ref={hostRef} className="react-chat-workspace-preview-code is-line-numbered">
      {windowed ? (
        <div className="react-chat-workspace-preview-hint">
          大文件仅显示第 {sliceStart + 1}–{sliceEnd} 行（目标：第 {focusLine} 行）
        </div>
      ) : null}
      {rendered.map((text, index) => {
        const no = sliceStart + index + 1
        const focused = no >= focusLine && no <= endLine
        return (
          <Fragment key={no}>
            <div
              data-line={no}
              className={`react-chat-workspace-preview-code-line${focused ? ' is-focus-line' : ''}`}
            >
              <span className="react-chat-workspace-preview-code-line-no">{no}</span>
              <span className="react-chat-workspace-preview-code-line-text">
                {text === '' ? '\u00A0' : text}
              </span>
            </div>
            {no === endLine && annotation ? (
              <div className="evf-code-annotation" data-testid="ws-code-annotation">
                <div className="evf-code-annotation-head">
                  {annotation.priority != null ? (
                    <span
                      className={`evf-code-annotation-badge${annotation.priority === 0 ? ' is-p0' : ''}`}
                    >
                      P{annotation.priority}
                    </span>
                  ) : null}
                  <span className="evf-code-annotation-title">{annotation.title || '评论'}</span>
                </div>
                {annotation.body ? (
                  <div className="evf-code-annotation-body">{annotation.body}</div>
                ) : null}
              </div>
            ) : null}
          </Fragment>
        )
      })}
    </div>
  )
}

function fileExtLabel(name: string, path: string): string {
  // Prefer whichever string has a real extension — display name may be a title without one.
  for (const candidate of [path, name]) {
    const m = String(candidate || '').match(/\.([a-z0-9]+)$/i)
    if (m) return m[1].toUpperCase()
  }
  return 'FILE'
}

function previewLooksLikeHtml(preview: WorkspacePreviewState): boolean {
  const path = preview.path || ''
  const name = preview.name || ''
  return (
    /\.(html?|htm)$/i.test(path) ||
    /\.(html?|htm)$/i.test(name) ||
    (!!preview.streaming && /^\s*</.test(preview.content || '')) ||
    /<!DOCTYPE|<html/i.test(preview.content || '')
  )
}

export function WorkspaceFilePreviewPane({
  preview,
  onClose,
  compact,
  embedded = false,
  contentZoom = 1,
  workspaceRoot = '',
  threadId = '',
  zoomControls = null,
  allowMarkdownEdit = false,
  onMarkdownChange,
  onRetry,
  focusLine,
  focusEndLine,
  focusAnnotation,
}: Props) {
  const focusLineNum = Number(focusLine) > 0 ? Number(focusLine) : 0
  const zoom = Math.min(2, Math.max(0.75, Number(contentZoom) || 1))
  const zoomStyle = { '--preview-zoom': String(zoom) } as CSSProperties
  const [markdownViewMode, setMarkdownViewMode] = useState<MarkdownViewMode>('preview')
  const [wrapLongLines, setWrapLongLines] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)

  const revealInFolder = useCallback(async () => {
    if (!preview?.path) return
    try {
      const { revealTaskOutputInFileManager } = await import('../../lib/task-output-preview.js')
      await revealTaskOutputInFileManager({
        path: preview.path,
        workspaceRoot,
      })
    } catch {
      /* toast handled inside helper */
    }
  }, [preview?.path, workspaceRoot, threadId])

  const copyPath = useCallback(async (text: string) => {
    const value = String(text || '').trim()
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      /* ignore */
    }
  }, [])

  const isMarkdown = useMemo(
    () =>
      !!(
        preview &&
        (isMarkdownDocumentPath(preview.path) || isMarkdownDocumentPath(preview.name))
      ),
    [preview],
  )
  const isHtml = useMemo(
    () => !!(preview && !preview.binary && !preview.error && !isMarkdown && previewLooksLikeHtml(preview)),
    [preview, isMarkdown],
  )

  const rawContent = preview && !preview.loading && !preview.error && !preview.binary ? preview.content : ''
  const streamBodyReady = useMemo(
    () =>
      !preview?.streaming ||
      isStreamWriteContentDisplayable({
        path: preview.path,
        content: rawContent,
        streaming: true,
      }),
    [preview, rawContent],
  )
  const streamDisplayActive = !!(preview?.streaming && rawContent.length > 0 && streamBodyReady)
  const displayContent = useThrottledValue(rawContent, 200, streamDisplayActive && isStreamThrottleEnabled())
  const htmlSrcDoc = useMemo(
    () => (displayContent ? prepareHtmlSrcDocForPreview(displayContent) : ''),
    [displayContent],
  )
  const htmlLivePreview = isHtml && !preview?.streaming
  const showStreamWaiting = !!(preview?.streaming && !preview.loading && !streamBodyReady && !isHtml)

  if (!preview) return null

  const displayPath = formatWorkspacePathForDisplay(preview.path)
  const pathSegments = String(displayPath || '')
    .replace(/\\/g, '/')
    .split('/')
    .filter(Boolean)
  const fileLabel = preview.name || pathSegments[pathSegments.length - 1] || '文件'
  const parentSegments = pathSegments.length > 1 ? pathSegments.slice(0, -1) : []
  const mediaSrc =
    preview.mediaSrc ||
    (isWorkspaceMediaBinaryPath(preview.path)
      ? resolveWorkspaceRelMediaSrc(workspaceRoot, preview.path)
      : '')
  const showImage = !!(mediaSrc && (preview.mediaKind === 'image' || isWorkspaceImagePath(preview.path)))
  const showVideo = !!(mediaSrc && (preview.mediaKind === 'video' || isWorkspaceVideoPath(preview.path)))
  const showAudio = !!(mediaSrc && (preview.mediaKind === 'audio' || isWorkspaceAudioPath(preview.path)))
  const showZoom = !embedded && zoomControls
  const canToggleMarkdown = isMarkdown && !preview.binary && !preview.error
  const canToggleWrap = !showImage && !showVideo && !showAudio && !preview.binary
  const hasLocalPath = !!(preview.path && !/^https?:\/\//i.test(preview.path))
  const showMarkdownPreview = canToggleMarkdown && markdownViewMode === 'preview'
  const showMarkdownSource = canToggleMarkdown && markdownViewMode === 'code'

  return (
    <div
      className={`react-chat-workspace-preview-pane${compact ? ' react-chat-workspace-preview-pane--compact' : ''}${
        embedded ? ' is-embedded' : ''
      }${preview.streaming ? ' is-streaming' : ''}${showStreamWaiting ? ' is-waiting' : ''}${
        zoom !== 1 ? ' has-content-zoom' : ''
      }${wrapLongLines ? ' is-wrap-lines' : ''}`}
      style={zoomStyle}
    >
      <div className="react-chat-workspace-preview-pane-header">
        <div className="react-chat-workspace-preview-breadcrumb" title={preview.path || fileLabel}>
          {parentSegments.map((segment, index) => (
            <Fragment key={`${segment}-${index}`}>
              <span className="react-chat-workspace-preview-crumb">{segment}</span>
              <span className="react-chat-workspace-preview-crumb-sep" aria-hidden>
                /
              </span>
            </Fragment>
          ))}
          <span className="react-chat-workspace-preview-crumb is-file">{fileLabel}</span>
          {preview.streaming ? (
            <span className="react-chat-workspace-preview-streaming-label">
              <span className="react-chat-workspace-preview-streaming-dot" aria-hidden />
              生成中
            </span>
          ) : null}
        </div>
        <div className="react-chat-workspace-preview-pane-header-actions">
          {showZoom ? (
            <div className="react-chat-workspace-preview-zoom-inline" aria-label="显示比例">
              <button
                type="button"
                className="react-chat-workspace-preview-zoom-btn"
                aria-label="缩小"
                title="缩小"
                disabled={!zoomControls.canZoomOut}
                onClick={zoomControls.onZoomOut}
              >
                −
              </button>
              <span className="react-chat-workspace-preview-zoom-value" aria-live="polite">
                {zoomControls.percent}%
              </span>
              <button
                type="button"
                className="react-chat-workspace-preview-zoom-btn"
                aria-label="放大"
                title="放大"
                disabled={!zoomControls.canZoomIn}
                onClick={zoomControls.onZoomIn}
              >
                +
              </button>
            </div>
          ) : null}
          <Popover open={moreOpen} onOpenChange={setMoreOpen}>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="react-chat-workspace-preview-icon-btn"
                title="更多"
                aria-label="更多"
                aria-haspopup="menu"
              >
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                  <circle cx="12" cy="12" r="1" />
                  <circle cx="19" cy="12" r="1" />
                  <circle cx="5" cy="12" r="1" />
                </svg>
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-52 p-1" role="menu">
              {canToggleMarkdown ? (
                <>
                  <div className="react-chat-workspace-preview-menu-label">Markdown</div>
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={markdownViewMode === 'preview'}
                    className={`react-chat-workspace-preview-menu-item${
                      markdownViewMode === 'preview' ? ' is-active' : ''
                    }`}
                    onClick={() => {
                      setMarkdownViewMode('preview')
                      setMoreOpen(false)
                    }}
                  >
                    预览
                  </button>
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={markdownViewMode === 'code'}
                    className={`react-chat-workspace-preview-menu-item${
                      markdownViewMode === 'code' ? ' is-active' : ''
                    }`}
                    onClick={() => {
                      setMarkdownViewMode('code')
                      setMoreOpen(false)
                    }}
                  >
                    原文
                  </button>
                  <div className="react-chat-workspace-preview-menu-sep" />
                </>
              ) : null}
              {canToggleWrap ? (
                <button
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={wrapLongLines}
                  className={`react-chat-workspace-preview-menu-item${wrapLongLines ? ' is-active' : ''}`}
                  onClick={() => {
                    setWrapLongLines((v) => !v)
                    setMoreOpen(false)
                  }}
                >
                  自动换行
                </button>
              ) : null}
              {hasLocalPath ? (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    className="react-chat-workspace-preview-menu-item"
                    onClick={() => {
                      void copyPath(preview.path)
                      setMoreOpen(false)
                    }}
                  >
                    复制路径
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="react-chat-workspace-preview-menu-item"
                    onClick={() => {
                      void copyPath(displayPath || preview.path)
                      setMoreOpen(false)
                    }}
                  >
                    复制相对路径
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="react-chat-workspace-preview-menu-item"
                    onClick={() => {
                      void revealInFolder()
                      setMoreOpen(false)
                    }}
                  >
                    在文件夹中显示
                  </button>
                </>
              ) : null}
            </PopoverContent>
          </Popover>
          {hasLocalPath ? (
            <button
              type="button"
              className="react-chat-workspace-preview-icon-btn"
              title="在文件夹中显示"
              aria-label="在文件夹中显示"
              onClick={() => void revealInFolder()}
            >
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </button>
          ) : null}
          {!embedded && onClose ? (
            <button
              type="button"
              className="react-chat-workspace-preview-pane-close"
              onClick={onClose}
              aria-label="关闭预览"
            >
              ×
            </button>
          ) : null}
        </div>
      </div>
      <div className="react-chat-workspace-preview-pane-body">
        {showStreamWaiting ? (
          <div className="react-chat-workspace-preview-waiting">
            <div className="react-chat-workspace-preview-waiting-spinner" aria-hidden />
            <p className="react-chat-workspace-preview-waiting-title">正在生成文件内容</p>
            <p className="react-chat-workspace-preview-waiting-hint">收到可读正文后将在此实时显示</p>
          </div>
        ) : preview.loading ? (
          <div className="react-chat-workspace-preview-waiting">
            <div className="react-chat-workspace-preview-waiting-spinner" aria-hidden />
            <p className="react-chat-workspace-preview-waiting-title">加载中</p>
          </div>
        ) : preview.error ? (
          <div className="react-chat-workspace-preview-error">
            <div className="react-chat-workspace-tree-error">{preview.error}</div>
            {onRetry ? (
              <button
                type="button"
                className="btn btn-secondary btn-sm react-chat-workspace-preview-retry-btn"
                onClick={() => onRetry()}
              >
                重试
              </button>
            ) : null}
          </div>
        ) : showImage ? (
          <div className="react-chat-workspace-preview-media-wrap">
            <button
              type="button"
              className="msg-tool-screenshot-btn react-chat-workspace-preview-media-btn"
              title="放大查看"
              aria-label="放大查看图片"
              onClick={() => showChatLightbox(mediaSrc)}
            >
              <img
                className="react-chat-workspace-preview-media-img"
                src={mediaSrc}
                alt={preview.name || '图片预览'}
              />
            </button>
          </div>
        ) : showVideo ? (
          <div className="react-chat-workspace-preview-media-wrap">
            <video
              className="react-chat-workspace-preview-media-video"
              src={mediaSrc}
              controls
              playsInline
              preload="metadata"
            />
          </div>
        ) : showAudio ? (
          <div className="react-chat-workspace-preview-media-wrap">
            <audio className="react-chat-workspace-preview-media-audio" src={mediaSrc} controls preload="metadata" />
          </div>
        ) : preview.binary ? (
          <div className="react-chat-workspace-preview-binary-hint">
            {getBinaryFilePreviewHint(preview.name, preview.path)}
          </div>
        ) : isHtml && htmlLivePreview ? (
          <div className="react-chat-workspace-preview-html-wrap">
            {preview.truncated ? (
              <div className="react-chat-workspace-preview-hint">仅显示前 512KB，完整内容请用 Agent 读取</div>
            ) : null}
            <iframe
              key={`${preview.path}-done`}
              className="react-chat-workspace-preview-html"
              title={`预览 ${preview.name}`}
              sandbox="allow-scripts allow-same-origin allow-forms allow-modals"
              srcDoc={htmlSrcDoc}
            />
          </div>
        ) : isHtml ? (
          <div className="react-chat-workspace-preview-code-wrap">
            {focusLineNum > 0 ? (
              <FocusedCodeBlock content={displayContent} focusLine={focusLineNum} focusEndLine={focusEndLine} annotation={focusAnnotation} />
            ) : (
              <pre className="react-chat-workspace-preview-code">
                <code>{displayContent}</code>
                {streamDisplayActive ? (
                  <span className="react-chat-workspace-typewriter-cursor" aria-hidden />
                ) : null}
              </pre>
            )}
          </div>
        ) : showMarkdownPreview ? (
          <div className="react-chat-workspace-preview-md-host">
            {preview.truncated ? (
              <div className="react-chat-workspace-preview-hint">仅显示前 512KB，完整内容请用 Agent 读取</div>
            ) : null}
            <MarkdownDocumentView
              text={displayContent}
              defaultMode="preview"
              allowEdit={allowMarkdownEdit && !preview.streaming}
              onChange={onMarkdownChange}
              readOnly={!!preview.streaming}
              hideModeSwitch
              testIdPrefix="ws-md"
            />
          </div>
        ) : showMarkdownSource || isMarkdown ? (
          <div className="react-chat-workspace-preview-code-wrap">
            {preview.truncated ? (
              <div className="react-chat-workspace-preview-hint">仅显示前 512KB，完整内容请用 Agent 读取</div>
            ) : null}
            <pre className="react-chat-workspace-preview-code">
              <code>{displayContent}</code>
            </pre>
          </div>
        ) : (
          <div className="react-chat-workspace-preview-code-wrap">
            {preview.truncated ? (
              <div className="react-chat-workspace-preview-hint">仅显示前 512KB，完整内容请用 Agent 读取</div>
            ) : null}
            {focusLineNum > 0 ? (
              <FocusedCodeBlock content={displayContent} focusLine={focusLineNum} focusEndLine={focusEndLine} annotation={focusAnnotation} />
            ) : (
              <pre className="react-chat-workspace-preview-code">
                <code>{displayContent}</code>
                {preview.streaming && streamBodyReady ? (
                  <span className="react-chat-workspace-typewriter-cursor" aria-hidden />
                ) : null}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

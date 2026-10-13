import { memo, useMemo, useCallback, useRef, useEffect, useState } from 'react'
import { Streamdown, defaultRehypePlugins, defaultRemarkPlugins } from 'streamdown'
import { code } from '@streamdown/code'
import { math } from '@streamdown/math'
import { cjk } from '@streamdown/cjk'
import { mermaid } from '@streamdown/mermaid'
import type { Components } from 'react-markdown'
import 'katex/dist/katex.min.css'
import 'streamdown/styles.css'
import { showChatLightbox } from '../../lib/chat-lightbox.js'
import { isImagePathLike } from '../../lib/chat-image-src.js'

/**
 * Streamdown wrapper for evopanel markdown rendering.
 * 
 * Provides:
 * - Custom component overrides for links, images, code, tables
 * - File path resolution (@@path@@ + #L123 syntax)
 * - Mermaid SVG caching
 * - Code comment integration
 * - Consistent styling with existing MarkdownHtml
 */

interface StreamdownRendererProps {
  text: string
  className?: string
  isStreaming?: boolean
  onOpenWorkspaceFile?: (
    rawPath: string,
    displayName?: string,
    opts?: {
      line?: number
      endLine?: number
      annotation?: { title?: string; body?: string; priority?: number }
    },
  ) => void
}

const MERMAID_SVG_CACHE_MAX = 32
const MERMAID_SVG_CACHE_MAX_CHARS = 1_000_000

const mermaidSvgCache = new Map<string, string>()

function mermaidSvgCacheGet(code: string): string | undefined {
  const key = String(code)
  if (mermaidSvgCache.has(key)) {
    const svg = mermaidSvgCache.get(key) as string
    mermaidSvgCache.delete(key)
    mermaidSvgCache.set(key, svg) // LRU touch
    return svg
  }
  return undefined
}

function mermaidSvgCacheSet(code: string, svg: string): void {
  const key = String(code)
  const val = String(svg)
  if (val.length > MERMAID_SVG_CACHE_MAX_CHARS) return
  if (mermaidSvgCache.has(key)) mermaidSvgCache.delete(key)
  mermaidSvgCache.set(key, val)
  if (mermaidSvgCache.size > MERMAID_SVG_CACHE_MAX) {
    const oldest = mermaidSvgCache.keys().next().value
    if (oldest !== undefined) mermaidSvgCache.delete(oldest)
  }
}

/**
 * Parse file path from @@path@@ syntax.
 * Also handles trailing #L123 line numbers.
 */
function parseFilePathFromMarkdown(href: string): { path: string; line?: number; endLine?: number } | null {
  if (!href) return null
  
  // Handle @@path@@ syntax
  const atsMatch = href.match(/^@@([^@]+)@@(?:#L(\d+)(?:-L(\d+))?)?$/)
  if (atsMatch) {
    const path = atsMatch[1]
    const line = atsMatch[2] ? Number(atsMatch[2]) : undefined
    const endLine = atsMatch[3] ? Number(atsMatch[3]) : undefined
    return { path, line, endLine }
  }
  
  // Handle direct paths with #L notation
  const hashMatch = href.match(/^([^#]+)#L(\d+)(?:-L(\d+))?$/)
  if (hashMatch) {
    const path = hashMatch[1]
    const line = Number(hashMatch[2])
    const endLine = hashMatch[3] ? Number(hashMatch[3]) : undefined
    return { path, line, endLine }
  }
  
  return null
}

function StreamdownRendererInner({
  text,
  className = 'msg-text',
  isStreaming = false,
  onOpenWorkspaceFile,
}: StreamdownRendererProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewSvg, setPreviewSvg] = useState('')
  const [previewScale, setPreviewScale] = useState(1)

  // Build custom components for all markdown elements
  const components = useMemo<Partial<Components>>(() => ({
    a: ({ href, children, node }) => {
      // File path resolution
      const fileInfo = href ? parseFilePathFromMarkdown(href) : null
      if (fileInfo) {
        return (
          <button
            type="button"
            data-evf-file-path={fileInfo.path}
            onClick={(e) => {
              e.preventDefault()
              if (onOpenWorkspaceFile) {
                const label = (typeof children === 'string'
                  ? children
                  : String(children)).replace(/^\s*📄\s*/, '').trim()
                onOpenWorkspaceFile(fileInfo.path, label || undefined, {
                  line: fileInfo.line,
                  endLine: fileInfo.endLine,
                })
              }
            }}
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              color: 'inherit',
              textDecoration: 'underline',
            }}
          >
            {children}
          </button>
        )
      }

      // Regular links
      if (href?.startsWith('http')) {
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        )
      }

      // Image path links
      if (href && isImagePathLike(href)) {
        return (
          <a
            href={href}
            onClick={(e) => {
              e.preventDefault()
              showChatLightbox(href)
            }}
            style={{ cursor: 'pointer' }}
          >
            {children}
          </a>
        )
      }

      return <span>{children}</span>
    },

    img: ({ src, alt, node }) => {
      if (!src) return null

      return (
        <img
          src={src}
          alt={alt || ''}
          className="msg-img"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            showChatLightbox(src)
          }}
          style={{ maxWidth: '100%', cursor: 'pointer' }}
        />
      )
    },

    // Keep existing code block rendering with Shiki (via @streamdown/code)
    // The plugin handles this automatically

    // Mermaid diagram click handling
    div: ({ node, children, className: divClassName, ...props }) => {
      const isMermaid = divClassName?.includes('mermaid')
      if (isMermaid && node?.children?.[0]?.type === 'element') {
        const svgStr = String(node.children[0]).match(/<svg[\s\S]*<\/svg>/)?.[0]
        return (
          <div
            className={divClassName}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              if (svgStr) {
                setPreviewSvg(svgStr)
                setPreviewScale(1)
                setPreviewOpen(true)
              }
            }}
            style={{ cursor: 'pointer' }}
            {...props}
          >
            {children}
          </div>
        )
      }
      return <div className={divClassName} {...props}>{children}</div>
    },
  }), [onOpenWorkspaceFile])

  const handlePreviewWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault()
    const step = e.deltaY < 0 ? 0.08 : -0.08
    setPreviewScale((s) => {
      const next = s + step
      if (next < 0.5) return 0.5
      if (next > 3) return 3
      return Number(next.toFixed(2))
    })
  }

  const previewModal = previewOpen && typeof document !== 'undefined'
    ? (
        <div
          className="react-chat-mermaid-modal"
          onClick={() => setPreviewOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            className="react-chat-mermaid-modal-panel"
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: 'white',
              borderRadius: '8px',
              padding: '16px',
              maxWidth: '90vw',
              maxHeight: '90vh',
            }}
          >
            <div className="react-chat-mermaid-modal-toolbar" style={{ marginBottom: '16px' }}>
              <button type="button" onClick={() => setPreviewScale((s) => Math.max(0.5, Number((s - 0.1).toFixed(2))))}>
                −
              </button>
              <span>{Math.round(previewScale * 100)}%</span>
              <button type="button" onClick={() => setPreviewScale((s) => Math.min(3, Number((s + 0.1).toFixed(2))))}>
                +
              </button>
              <button type="button" onClick={() => setPreviewScale(1)}>
                重置
              </button>
              <button type="button" onClick={() => setPreviewOpen(false)}>
                关闭
              </button>
            </div>
            <div
              className="react-chat-mermaid-modal-canvas"
              onWheel={handlePreviewWheel}
              style={{
                overflow: 'auto',
                maxHeight: 'calc(90vh - 60px)',
              }}
            >
              <div
                className="react-chat-mermaid-modal-svg"
                style={{
                  transform: `scale(${previewScale})`,
                  transformOrigin: 'top center',
                  display: 'inline-block',
                }}
                dangerouslySetInnerHTML={{ __html: previewSvg }}
              />
            </div>
          </div>
        </div>
      )
    : null

  return (
    <>
      <div ref={rootRef} className={className}>
        <Streamdown
          plugins={{ code, math, cjk, mermaid }}
          remarkPlugins={Object.values(defaultRemarkPlugins)}
          rehypePlugins={Object.values(defaultRehypePlugins)}
          components={components}
          // Table actions belong to the surrounding module toolbar, not inside
          // the assistant message body. Keep Markdown tables read-only here.
          controls={{ table: false }}
          isAnimating={isStreaming}
          parseIncompleteMarkdown
        >
          {text}
        </Streamdown>
      </div>
      {previewModal}
    </>
  )
}

export const StreamdownRenderer = memo(StreamdownRendererInner)

import { createPortal } from 'react-dom'
import { useModalEscapeClose } from '../hooks/useModalEscapeClose.js'
import {
  WorkspaceFilePreviewPanel,
  type WorkspaceFilePreviewPanelProps,
} from './WorkspaceFilePreviewPanel.js'

type Props = WorkspaceFilePreviewPanelProps & {
  onClose: () => void
}

/** 弹窗兜底：正式路径已迁到右栏 `file` 标签。 */
export function WorkspaceFilePreviewModal({ onClose, ...panelProps }: Props) {
  useModalEscapeClose(onClose)

  if (typeof document === 'undefined') return null

  const name = panelProps.name || panelProps.path

  return createPortal(
    <div
      className="react-chat-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label={`查看文件 ${name}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="react-chat-modal-card react-chat-workspace-preview-card"
        onClick={(e) => e.stopPropagation()}
      >
        <WorkspaceFilePreviewPanel {...panelProps} onClose={onClose} />
      </div>
    </div>,
    document.body,
  )
}

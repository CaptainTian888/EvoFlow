import type { ReactNode } from 'react'
import type { RightStageKind, RightStageSurface } from './right-stage-types.js'

export type RightStageKindRenderProps = {
  surface: RightStageSurface
  onClose: () => void
  /** 是否为当前激活标签；原生 WebView2 需据此停靠/恢复，不能只靠 CSS hidden。 */
  active: boolean
}

export type RightStageKindDefinition = {
  kind: RightStageKind
  render: (props: RightStageKindRenderProps) => ReactNode
}

const registry = new Map<string, RightStageKindDefinition>()

export function registerRightStageKind(def: RightStageKindDefinition) {
  registry.set(String(def.kind), def)
}

export function getRightStageKind(kind: string): RightStageKindDefinition | null {
  return registry.get(String(kind || '')) || null
}

export function listRegisteredRightStageKinds(): string[] {
  return [...registry.keys()]
}

export function UnknownStageKind({ kind }: { kind: string }) {
  return (
    <aside className="react-chat-right-stage-panel react-chat-right-stage-unknown" role="region">
      <header className="react-chat-right-stage-header">
        <span className="react-chat-right-stage-title">未知 Stage</span>
      </header>
      <div className="react-chat-right-stage-body">
        <p className="react-chat-right-stage-unknown-text">未注册的 kind: {kind}</p>
      </div>
    </aside>
  )
}

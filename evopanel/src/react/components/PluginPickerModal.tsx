import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import '@/styles-bridge.css'
import { gatewayProxy } from '../../lib/tauri-api.js'
import { resolvePluginIconSource } from '@/lib/pluginIconSource.js'

export type PluginPickerItem = {
  id: string
  name: string
  label: string
  description: string
  version?: string
  marketplace: string
  componentTypes?: string[]
  iconUrl?: string
}
export type PluginSelection = { id: string; label: string; iconUrl?: string }

export type PluginCatalogItem = {
  id: string
  name: string
  marketplace: string
  description?: string
  version?: string
  enabled: boolean
  installed: boolean
  componentTypes?: string[]
  listing?: { displayName?: string; icon?: string } | null
}

/** 拉取已安装且启用的插件（供聊天「+」插件选择器使用）。 */
export async function fetchEnabledPlugins(): Promise<PluginPickerItem[]> {
  // 桌面端必须走 gatewayProxy，裸 fetch 相对 /api 会拿到 SPA HTML。
  const body = (await gatewayProxy('GET', '/api/plugins/overview')) as {
    installedPlugins?: PluginCatalogItem[]
  }
  const rows = body.installedPlugins ?? []
  return rows
    .filter((row) => row.enabled !== false)
    .map((row) => ({
      id: row.id,
      name: row.name,
      label: row.listing?.displayName || row.name,
      description: row.description || '',
      version: row.version,
      marketplace: row.marketplace,
      componentTypes: row.componentTypes,
      iconUrl: row.listing?.icon || undefined,
    }))
}

const COMPONENT_BADGES: Record<string, string> = {
  commands: '命令',
  skills: '技能',
  agents: '智能体',
  mcpServers: 'MCP',
  hooks: '钩子',
}

/**
 * 插件多选弹窗（ZCode UI 风格）。
 * 视觉走 zcode-ui 的原版设计 token（styles-bridge.css：@theme + utilities，
 * 无 preflight、全局规则收窄到 .zcode-bridge-root，不影响 EvoFlow 宿主）。
 * 列表形态对齐 ZCode 插件市场卡片：图标方块 + 显示名 + 描述 + 能力徽标，
 * 选中态用 ZCode 的 check 圆点；行为与 SkillPickerModal 一致（多选、确定回写）。
 */
export function PluginPickerModal({
  open,
  onClose,
  plugins,
  loading,
  selected,
  onConfirm,
  onManage,
}: {
  open: boolean
  onClose: () => void
  plugins: PluginPickerItem[]
  loading: boolean
  selected: PluginSelection[]
  onConfirm: (next: PluginSelection[]) => void
  onManage?: () => void
}) {
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState<PluginSelection[]>(selected)
  const searchRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (open) queueMicrotask(() => setDraft(selected))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const t = window.setTimeout(() => searchRef.current?.focus(), 0)
    return () => window.clearTimeout(t)
  }, [open])

  if (!open || typeof document === 'undefined') return null

  const filtered = plugins.filter((p) => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return (
      String(p.name || '').toLowerCase().includes(q) ||
      String(p.label || '').toLowerCase().includes(q) ||
      String(p.description || '').toLowerCase().includes(q)
    )
  })

  const isSelected = (id: string) => draft.some((p) => p.id === id)
  const toggle = (p: PluginPickerItem) => {
    setDraft((prev) =>
      isSelected(p.id)
        ? prev.filter((x) => x.id !== p.id)
        : [...prev, { id: p.id, label: p.label || p.name, iconUrl: p.iconUrl }],
    )
  }
  const removeChip = (id: string) => setDraft((prev) => prev.filter((x) => x.id !== id))
  const clearAll = () => setDraft([])

  const componentBadges = (types?: string[]) => {
    if (!types?.length) return null
    return types.map((t) => (
      <span
        key={t}
        className="rounded-md border border-border bg-muted px-1.5 py-0.5 text-ui-xs text-foreground-subtle"
      >
        {COMPONENT_BADGES[t] || t}
      </span>
    ))
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="选择插件"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="zcode-bridge-root flex max-h-[80vh] w-[560px] max-w-[92vw] flex-col overflow-hidden rounded-xl border border-border bg-background text-foreground shadow-xl">
        {/* 头部 — ZCode 设置页标题风格 */}
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 pb-3 pt-4">
          <div className="min-w-0">
            <div className="text-ui-base font-semibold text-foreground">选择插件</div>
            <div className="mt-0.5 text-ui-sm text-foreground-subtle">
              可多选 · 所选插件的命令与技能在本轮对话生效
            </div>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-foreground-subtle transition-colors hover:bg-hover hover:text-foreground"
            onClick={onClose}
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-5 py-4">
          {/* 搜索 — ZCode SettingsSearchInput 风格 */}
          <div className="relative">
            <input
              ref={searchRef}
              type="search"
              className="h-8 w-full rounded-lg border border-border bg-surface px-3 text-ui-sm text-foreground outline-none placeholder:text-foreground-subtlest focus:border-border-focus"
              placeholder="搜索插件…"
              value={query}
              aria-label="搜索插件"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
            />
          </div>

          {/* 已选 chips — ZCode chip 风格 */}
          {draft.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {draft.map((p) => {
                const iconSrc = resolvePluginIconSource(p.id, p.iconUrl)
                return (
                  <span
                    key={p.id}
                    className="flex items-center gap-1 rounded-full border border-border bg-surface py-0.5 pl-2 pr-1 text-ui-sm text-foreground"
                  >
                    <span aria-hidden className="flex h-3.5 w-3.5 items-center justify-center overflow-hidden">
                      {iconSrc ? (
                        <img src={iconSrc} alt="" className="h-3.5 w-3.5 object-contain" />
                      ) : (
                        <span aria-hidden>🧩</span>
                      )}
                    </span>
                    <span>{p.label}</span>
                    <button
                      type="button"
                      className="ml-0.5 rounded-full px-1 text-foreground-subtle hover:bg-hover hover:text-foreground"
                      aria-label={`移除 ${p.label}`}
                      onClick={() => removeChip(p.id)}
                    >
                      ×
                    </button>
                  </span>
                )
              })}
              <button
                type="button"
                className="rounded-full px-2 py-0.5 text-ui-sm text-foreground-subtle hover:bg-hover hover:text-foreground"
                onClick={clearAll}
              >
                清空
              </button>
            </div>
          ) : null}

          {/* 列表 — ZCode 插件市场卡片风格 */}
          <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-0.5">
            {loading ? (
              <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-ui-sm text-foreground-subtle">
                加载中…
              </div>
            ) : plugins.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-ui-sm text-foreground-subtle">
                暂无已启用插件 — 前往「设置 → 插件市场」安装
              </div>
            ) : filtered.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-ui-sm text-foreground-subtle">
                无匹配插件
              </div>
            ) : (
              filtered.map((p) => {
                const active = isSelected(p.id)
                const iconSrc = resolvePluginIconSource(p.id, p.iconUrl)
                return (
                  <button
                    key={p.id}
                    type="button"
                    className={`flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                      active
                        ? 'border-border-focus bg-selected'
                        : 'border-transparent bg-surface hover:bg-hover'
                    }`}
                    onClick={() => toggle(p)}
                  >
                    <span
                      className={`mt-0.5 flex h-8 w-8 flex-none items-center justify-center overflow-hidden rounded-lg ${
                        active ? 'bg-background' : 'bg-hover'
                      }`}
                      aria-hidden
                    >
                      {iconSrc ? (
                        <img src={iconSrc} alt="" className="h-5 w-5 object-contain" />
                      ) : (
                        <span className="text-base" aria-hidden>
                          🧩
                        </span>
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-ui-sm font-medium text-foreground">
                          {p.label || p.name}
                        </span>
                        {p.version ? (
                          <span className="flex-none text-ui-xs text-foreground-subtlest">
                            v{p.version}
                          </span>
                        ) : null}
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-ui-sm text-foreground-subtle">
                        {p.description || '暂无描述'}
                      </span>
                      {p.componentTypes?.length ? (
                        <span className="mt-1 flex flex-wrap gap-1">
                          {componentBadges(p.componentTypes)}
                        </span>
                      ) : null}
                    </span>
                    <span
                      className={`mt-1 flex h-4 w-4 flex-none items-center justify-center rounded-full border text-[10px] ${
                        active
                          ? 'border-transparent bg-foreground text-background'
                          : 'border-border text-transparent'
                      }`}
                      aria-hidden
                    >
                      ✓
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </div>

        {/* 底部操作 — ZCode 按钮风格 */}
        <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
          <span className="text-ui-sm text-foreground-subtle">
            {draft.length > 0 ? `已选 ${draft.length} 个插件` : '未选择'}
          </span>
          <span className="flex items-center gap-2">
            {onManage ? (
              <button
                type="button"
                className="rounded-lg border border-border px-3 py-1.5 text-ui-sm text-foreground transition-colors hover:bg-hover"
                onClick={() => {
                  onClose()
                  onManage()
                }}
              >
                管理插件…
              </button>
            ) : null}
            <button
              type="button"
              className="rounded-lg border border-border px-3 py-1.5 text-ui-sm text-foreground transition-colors hover:bg-hover"
              onClick={onClose}
            >
              取消
            </button>
            <button
              type="button"
              className="rounded-lg bg-foreground px-3 py-1.5 text-ui-sm font-medium text-background transition-opacity hover:opacity-90"
              onClick={() => {
                onConfirm(draft)
                onClose()
              }}
            >
              确定{draft.length > 0 ? `（${draft.length}）` : ''}
            </button>
          </span>
        </div>
      </div>
    </div>,
    document.body,
  )
}

import { useState } from 'react'
import { resolvePluginIconSource } from '../../zcode-ui/lib/pluginIconSource.js'

/** 已选插件 pill 图标；img 加载失败（CDN 不可达 / 图标文件缺失）回退 🧩，避免裂图。 */
export function PluginPillIcon({ pluginId, iconUrl }: { pluginId: string; iconUrl?: string }) {
  const [failed, setFailed] = useState(false)
  const iconSrc = resolvePluginIconSource(pluginId, iconUrl)
  if (!iconSrc || failed) return <>🧩</>
  return (
    <img
      src={iconSrc}
      alt=""
      className="react-chat-skill-composer-pill-icon-img"
      draggable={false}
      onError={() => setFailed(true)}
    />
  )
}
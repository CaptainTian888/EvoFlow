import documentsIconUrl from "@/assets/plugin-icons/documents.png";
import imageSearchIconUrl from "@/assets/plugin-icons/image-search.png";
import pdfIconUrl from "@/assets/plugin-icons/pdf.png";
import pluginCreatorIconUrl from "@/assets/plugin-icons/plugin-creator.png";
import presentationsIconUrl from "@/assets/plugin-icons/presentations.png";
import spreadsheetsIconUrl from "@/assets/plugin-icons/spreadsheets.png";
import { apiUrl } from "@/lib/api-client.js";
import { isTrustedImageUrl } from "@/lib/trustedImageUrl.js";

const OFFICIAL_PLUGIN_ICON_BY_ID: Readonly<Record<string, string>> = {
  "documents@zcode-plugins-official": documentsIconUrl,
  "image-search@zcode-plugins-official": imageSearchIconUrl,
  "pdf@zcode-plugins-official": pdfIconUrl,
  "plugin-creator@zcode-plugins-official": pluginCreatorIconUrl,
  "presentations@zcode-plugins-official": presentationsIconUrl,
  "spreadsheets@zcode-plugins-official": spreadsheetsIconUrl,
};

// EvoFlow 官方市场 id 复用同一批打包图标（与 ZCode 官方内置插件一一对应）。
const EVOFLOW_OFFICIAL_ICON_BY_ID: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(OFFICIAL_PLUGIN_ICON_BY_ID).map(([id, url]) => [
    id.replace("@zcode-plugins-official", "@evoflow-plugins-official"),
    url,
  ]),
);
const OFFICIAL_ICON_BY_ID: Readonly<Record<string, string>> = {
  ...OFFICIAL_PLUGIN_ICON_BY_ID,
  ...EVOFLOW_OFFICIAL_ICON_BY_ID,
};

const TRUSTED_BUNDLED_PLUGIN_ICONS = new Set(Object.values(OFFICIAL_ICON_BY_ID));

/** 按完整身份解析客户端自有图标，避免商店、候选和消息各自维护不同例外。 */
export function resolvePluginIconSource(
  pluginId: string | undefined,
  icon?: string,
  /** 仅用于在 Gateway 地址就绪后触发调用方重渲染。 */
  _iconEpoch?: number,
): string | undefined {
  if (pluginId) {
    const bundledIcon = OFFICIAL_ICON_BY_ID[pluginId];
    if (bundledIcon) return bundledIcon;
  }
  if (!isTrustedImageUrl(icon)) return undefined;
  return localizeGatewayIcon(icon);
}

/** 桌面端 WebView 的页面源不是 Gateway，相对 `/api/plugins/icon/` 会 404。 */
function localizeGatewayIcon(icon: string): string {
  if (!icon.startsWith("/api/plugins/icon/")) return icon;
  try {
    return apiUrl(icon.slice("/api".length));
  } catch {
    return icon;
  }
}

/** Session 投影已完成身份匹配；仅放行固定打包资源，不放宽任意本地 URL。 */
export function isTrustedPluginIconSource(icon: string | undefined): icon is string {
  return Boolean(icon && TRUSTED_BUNDLED_PLUGIN_ICONS.has(icon)) || isTrustedImageUrl(icon);
}

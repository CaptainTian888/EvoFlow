/** UI 远端图片只允许 HTTPS；失败时由各展示组件回退到本地图标。
 * 同源的插件图标端点（/api/plugins/icon/，由 Gateway 本地供给）同样放行。
 * 桌面端会把该端点改写成 http://127.0.0.1:<gateway>/api/plugins/icon/，只放行本机回环。 */
export function isTrustedImageUrl(url: string | undefined): url is string {
  if (typeof url !== "string" || !url) return false;
  if (url.startsWith("https://") || url.startsWith("/api/plugins/icon/")) return true;
  return isLoopbackPluginIconUrl(url);
}

function isLoopbackPluginIconUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    if (parsed.hostname !== "127.0.0.1" && parsed.hostname !== "localhost") return false;
    return parsed.pathname.startsWith("/api/plugins/icon/");
  } catch {
    return false;
  }
}

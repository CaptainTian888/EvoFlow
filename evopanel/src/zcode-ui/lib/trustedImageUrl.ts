/** UI 远端图片只允许 HTTPS；失败时由各展示组件回退到本地图标。
 * 同源的插件图标端点（/api/plugins/icon/，由 Gateway 本地供给）同样放行。 */
export function isTrustedImageUrl(url: string | undefined): url is string {
  return (
    typeof url === "string" &&
    (url.startsWith("https://") || url.startsWith("/api/plugins/icon/"))
  );
}

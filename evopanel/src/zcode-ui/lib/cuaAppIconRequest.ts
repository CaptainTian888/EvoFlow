import type { ApplicationIconRequest } from "@zcode/shared";

/**
 * producer 的 `appKey` → 平台图标 locator。
 *
 * `appKey` 由 zcode-cua 的 `deriveApplicationKey` 生成，形态是 `<scheme>:<value>`：
 * `darwin:<bundleId>`（小写）、`windows-aumid:<aumid>`、`windows-exe:<canonical path>`、
 * `linux-exe:<path>`。会话协议只承载这个字符串，图标字节由平台服务按 locator 现取。
 *
 * Linux 没有对应的 `ApplicationIconLocator` kind，desktop 侧也没有 resolver，返回 null 让
 * 调用方回退自己的通用图标。
 */
const APP_KEY_LOCATOR_KINDS = {
  darwin: "darwin-bundle-id",
  "windows-aumid": "windows-aumid",
  "windows-exe": "windows-executable-path",
} as const satisfies Record<string, ApplicationIconRequest["locators"][number]["kind"]>;

export function cuaAppKeyToIconRequest(
  appKey: string | undefined | null,
): ApplicationIconRequest | null {
  if (!appKey) return null;
  // 只切第一个冒号：Windows 的 exe 路径本身带盘符冒号，全局 split 会把 `c:\...` 截成 `c`。
  const separator = appKey.indexOf(":");
  if (separator <= 0) return null;
  const scheme = appKey.slice(0, separator);
  const value = appKey.slice(separator + 1).trim();
  if (!value) return null;
  const kind = (APP_KEY_LOCATOR_KINDS as Record<string, string | undefined>)[scheme];
  if (!kind) return null;
  return { locators: [{ kind, value } as ApplicationIconRequest["locators"][number]] };
}

const LOCATOR_KIND_TO_APP_KEY_SCHEME: Record<string, string> = {
  "darwin-bundle-id": "darwin",
  "windows-aumid": "windows-aumid",
  "windows-executable-path": "windows-exe",
};

/** 面板 kind:"cua" targetApp.iconLocators → producer appKey（供 Node REPL 卡复用）。 */
export function cuaIconLocatorsToAppKey(
  locators: ReadonlyArray<{ kind?: string; value?: string }> | null | undefined,
): string | null {
  if (!locators?.length) return null;
  for (const locator of locators) {
    const kind = typeof locator?.kind === "string" ? locator.kind : "";
    const value = typeof locator?.value === "string" ? locator.value.trim() : "";
    const scheme = LOCATOR_KIND_TO_APP_KEY_SCHEME[kind];
    if (scheme && value) return `${scheme}:${value}`;
  }
  return null;
}

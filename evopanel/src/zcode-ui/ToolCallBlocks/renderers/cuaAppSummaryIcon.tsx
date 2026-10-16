import { useEffect, useState, type ReactNode } from "react";
import type { ApplicationIconRequest } from "@zcode/shared";
import { cn } from "@/components/lib/utils.js";
import { useOptionalPlatform } from "@/hooks/usePlatform.js";
import { CUA_TOOL_ICON } from "@/ToolCallBlocks/renderers/cuaIcon.js";

export function CuaAppSummaryIcon({
  bundleId,
  fallback,
  iconRequest,
  name,
  className,
}: {
  bundleId?: string;
  /**
   * 图标取不到时显示什么（平台无 resolver、Linux 无 locator、读取失败）。
   * 默认沿用 CUA 图标；node_repl 工具卡传入自己的图标，避免同一张卡在解析失败时
   * 跳成另一个指针图形。
   */
  fallback?: ReactNode;
  iconRequest?: ApplicationIconRequest | string | null;
  name: string;
  className?: "size-4" | "size-5";
}) {
  const platform = useOptionalPlatform();
  const [iconDataUrl, setIconDataUrl] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setIconDataUrl(null);
    const request = iconRequest ?? bundleId;
    if (!request) return () => undefined;
    const resolve = async (): Promise<string | null> => {
      // 平台原生 resolver 优先（ZCode 桌面语义）；EvoFlow 无实现时兜底走网关
      // /api/cua/app-icon（PowerShell 按 locator 提取）。字符串形式是旧 bundle_id，
      // 无法构造 locator，交回调用方的 fallback 图形。
      if (typeof request !== "string" && platform?.getApplicationIcon) {
        try {
          const result = await platform.getApplicationIcon(request);
          if (result?.iconDataUrl) return result.iconDataUrl;
        } catch {
          // 平台实现失败 → 继续网关兜底
        }
      }
      if (typeof request === "string") return null;
      try {
        const response = await fetch("/api/cua/app-icon", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request),
        });
        if (!response.ok) return null;
        const result = (await response.json()) as { iconDataUrl?: string } | null;
        return result?.iconDataUrl ?? null;
      } catch {
        return null;
      }
    };
    void resolve().then((dataUrl) => {
      if (active) setIconDataUrl(dataUrl);
    });
    return () => {
      active = false;
    };
  }, [bundleId, iconRequest, platform]);

  return iconDataUrl ? (
    <img
      src={iconDataUrl}
      alt={name}
      className={cn(className ?? "size-4", "shrink-0 rounded-sm object-contain")}
    />
  ) : (
    (fallback ?? CUA_TOOL_ICON)
  );
}

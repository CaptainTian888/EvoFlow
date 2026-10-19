import { useEffect, useState, type ReactNode } from "react";
import { Blocks } from "lucide-react";
import { cn } from "@/components/lib/utils.js";
import { getGatewayBaseUrl } from "@/lib/api-client.js";
import { resolvePluginIconSource } from "@/lib/pluginIconSource.js";

/** Plugin 原始图标；支持官方内置图标与 HTTPS，缺失或失败时使用调用方兜底，默认回退 Blocks。 */
export function PluginIcon({
  src,
  pluginId,
  className,
  iconClassName,
  fallbackIcon,
}: {
  src?: string;
  pluginId?: string;
  className?: string;
  iconClassName?: string;
  fallbackIcon?: ReactNode;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const [iconEpoch, setIconEpoch] = useState(0);
  useEffect(() => {
    let cancelled = false;
    void getGatewayBaseUrl().then(() => {
      if (!cancelled) setIconEpoch((n) => n + 1);
    });
    return () => {
      cancelled = true;
    };
  }, [src, pluginId]);
  const resolvedSrc = resolvePluginIconSource(pluginId, src, iconEpoch);
  const showImage = Boolean(resolvedSrc) && !imageFailed;
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex shrink-0 select-none items-center justify-center rounded-xl bg-surface",
        !showImage && "text-foreground-subtle",
        className,
      )}
    >
      {showImage ? (
        <img
          src={resolvedSrc}
          alt=""
          draggable={false}
          className="h-2/3 w-2/3 object-contain"
          onError={() => setImageFailed(true)}
        />
      ) : fallbackIcon ? (
        fallbackIcon
      ) : (
        <Blocks className={cn("size-4", iconClassName)} />
      )}
    </span>
  );
}

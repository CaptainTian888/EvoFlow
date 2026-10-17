/**
 * EvoFlow Plugin Management Service — HTTP client.
 *
 * Implements the vendored `IPluginManagementService` (the thin settings-page
 * service from `@/services/plugins/pluginManagement.ts`) against the EvoFlow
 * Gateway `/api/plugins/*` REST API, which is the Python port of the ZCode
 * CLI plugin adapters. The Gateway returns the exact `zcode-protocol` wire
 * shapes, so most methods are pass-throughs.
 *
 * Source lineage: ZCode/packages/services/src/plugins/pluginManagementService.ts
 * (agent-backed implementation) → EvoFlow HTTP-backed implementation.
 */

import { Event } from "@zcode/rpc";
import { blog } from "../../lib/browser-unified-log.js";
import { gatewayProxy } from "../../lib/tauri-api.js";
import type {
  ZCodePluginOperationProgressNotification,
  ZCodePluginsCancelOperationResult,
  ZCodePluginsConfigureResult,
  ZCodePluginsDescribeResult,
  ZCodePluginsInstallResult,
  ZCodePluginsListResult,
  ZCodePluginsMarketplaceMutationResult,
  ZCodePluginsOverviewResult,
  ZCodePluginsReferenceCatalogResult,
  ZCodePluginsRestoreBuiltinResult,
  ZCodePluginsSetEnabledResult,
  ZCodePluginsUninstallResult,
  ZCodePluginsValidateResult,
  ZCodePluginsResolveSuggestedReferenceResult,
} from "@zcode/shared";
import type { IPluginManagementService } from "./pluginManagement.js";
import type {
  ZCodeAgentAddPluginMarketplaceParams,
  ZCodeAgentCancelPluginOperationParams,
  ZCodeAgentConfigurePluginParams,
  ZCodeAgentDescribePluginParams,
  ZCodeAgentInstallPluginParams,
  ZCodeAgentPluginReferenceCatalogParams,
  ZCodeAgentPluginViewParams,
  ZCodeAgentRemovePluginMarketplaceParams,
  ZCodeAgentResetPluginConfigParams,
  ZCodeAgentResolveSuggestedPluginReferenceParams,
  ZCodeAgentRestoreBuiltinPluginParams,
  ZCodeAgentSetPluginEnabledParams,
  ZCodeAgentUninstallPluginParams,
  ZCodeAgentUpdatePluginMarketplaceParams,
  ZCodeAgentUpdatePluginParams,
  ZCodeAgentValidatePluginParams,
} from "../zcode-agent/zcodeAgentPluginParams.js";

/**
 * 桌面端必须走 gatewayProxy（Rust / pipe），不能裸 fetch 相对 /api/*：
 * webview 同源会回 SPA HTML，JSON.parse 就会报 Unexpected token '<' / DOCTYPE。
 */
async function httpGet<T>(
  url: string,
  query?: Record<string, unknown> | null,
): Promise<T> {
  return (await gatewayProxy("GET", url, null, query ?? null)) as T;
}

async function httpSend<T>(
  url: string,
  method: string,
  body?: unknown,
  query?: Record<string, unknown> | null,
): Promise<T> {
  // 插件操作（安装/启停/卸载/配置/市场变更）进统一日志，与后端 service 日志对齐。
  const bodyPreview = body !== undefined ? JSON.stringify(body).slice(0, 160) : "";
  blog("info", `[plugin-client] ${method} ${url}${bodyPreview ? ` body=${bodyPreview}` : ""}`);
  const started = Date.now();
  try {
    const result = (await gatewayProxy(method, url, body ?? null, query ?? null)) as T;
    blog("info", `[plugin-client] ${method} ${url} ok in ${Date.now() - started}ms`);
    return result;
  } catch (err) {
    blog("warn", `[plugin-client] ${method} ${url} FAILED in ${Date.now() - started}ms: ${err}`);
    throw err;
  }
}

function encodePathSegment(value: string): string {
  return encodeURIComponent(value);
}

export class EvoflowPluginManagementClient implements IPluginManagementService {
  async listPlugins(_params: ZCodeAgentPluginViewParams): Promise<ZCodePluginsListResult> {
    return httpGet<ZCodePluginsListResult>("/api/plugins/list");
  }

  async getPluginsOverview(
    _params: ZCodeAgentPluginViewParams,
  ): Promise<ZCodePluginsOverviewResult> {
    return httpGet<ZCodePluginsOverviewResult>("/api/plugins/overview");
  }

  async getPluginReferenceCatalog(
    _params: ZCodeAgentPluginReferenceCatalogParams,
  ): Promise<ZCodePluginsReferenceCatalogResult> {
    return httpGet<ZCodePluginsReferenceCatalogResult>("/api/plugins/reference-catalog");
  }

  async resolveSuggestedPluginReference(
    params: ZCodeAgentResolveSuggestedPluginReferenceParams,
  ): Promise<ZCodePluginsResolveSuggestedReferenceResult> {
    const slug = (params as { slug?: string; pluginName?: string }).slug
      ?? (params as { pluginName?: string }).pluginName
      ?? "";
    const marketplace = (params as { marketplace?: string }).marketplace ?? "";
    if (!slug || !marketplace) {
      return { stableId: slug, status: "unavailable", diagnostics: [] };
    }
    const overview = await httpGet<ZCodePluginsOverviewResult>("/api/plugins/overview");
    const pluginId = `${slug}@${marketplace}`;
    const installed = overview.installedPlugins.find((item) => item.id === pluginId);
    if (installed) {
      return {
        stableId: pluginId,
        status: installed.enabled ? "ready" : "disabled",
        marketplace,
        pluginName: slug,
        sourceTrust: "official",
        diagnostics: [],
      };
    }
    const available = overview.availablePlugins.find((item) => item.id === pluginId);
    if (available) {
      return {
        stableId: pluginId,
        status: "ready",
        marketplace,
        pluginName: slug,
        sourceTrust: "official",
        diagnostics: [],
      };
    }
    return { stableId: pluginId, status: "missing", diagnostics: [] };
  }

  onDynamicPluginOperationProgress(
    _operationId: string,
  ): Event<ZCodePluginOperationProgressNotification> {
    // 安装/刷新是同步 HTTP 请求，没有进度事件流；给一个空订阅保持接口形状。
    return Event.None;
  }

  async addPluginMarketplace(
    params: ZCodeAgentAddPluginMarketplaceParams,
  ): Promise<ZCodePluginsMarketplaceMutationResult> {
    return httpSend<ZCodePluginsMarketplaceMutationResult>(
      "/api/plugins/marketplaces",
      "POST",
      { source: params.source },
    );
  }

  async removePluginMarketplace(
    params: ZCodeAgentRemovePluginMarketplaceParams,
  ): Promise<ZCodePluginsMarketplaceMutationResult> {
    return httpSend<ZCodePluginsMarketplaceMutationResult>(
      `/api/plugins/marketplaces/${encodePathSegment(params.marketplace)}`,
      "DELETE",
    );
  }

  async updatePluginMarketplace(
    params: ZCodeAgentUpdatePluginMarketplaceParams,
  ): Promise<ZCodePluginsMarketplaceMutationResult> {
    if (!params.marketplace) {
      // 全量刷新：逐个刷新由后端支持，这里统一走单市场刷新入口的批量语义。
      const overview = await httpGet<ZCodePluginsOverviewResult>("/api/plugins/overview");
      const diagnostics: ZCodePluginsMarketplaceMutationResult["diagnostics"] = [];
      for (const marketplace of overview.marketplaces) {
        try {
          const result = await httpSend<{ diagnostics: ZCodePluginsMarketplaceMutationResult["diagnostics"] }>(
            `/api/plugins/marketplaces/${encodePathSegment(marketplace.id)}/refresh`,
            "POST",
          );
          diagnostics.push(...(result.diagnostics ?? []));
        } catch (error) {
          diagnostics.push({
            code: "plugin_marketplace_invalid",
            message: error instanceof Error ? error.message : String(error),
            severity: "error",
            pluginId: marketplace.id,
          });
        }
      }
      return { diagnostics };
    }
    const result = await httpSend<{ diagnostics: ZCodePluginsMarketplaceMutationResult["diagnostics"] }>(
      `/api/plugins/marketplaces/${encodePathSegment(params.marketplace)}/refresh`,
      "POST",
    );
    return { diagnostics: result.diagnostics };
  }

  async installPlugin(params: ZCodeAgentInstallPluginParams): Promise<ZCodePluginsInstallResult> {
    return httpSend<ZCodePluginsInstallResult>("/api/plugins/install", "POST", {
      pluginName: params.pluginName,
      marketplace: params.marketplace,
      scope: params.scope ?? "user",
    });
  }

  async cancelPluginOperation(
    params: ZCodeAgentCancelPluginOperationParams,
  ): Promise<ZCodePluginsCancelOperationResult> {
    // HTTP 请求没有可取消的 operation；按“已结束”回包。
    return { operationId: params.operationId, cancelled: false };
  }

  async uninstallPlugin(
    params: ZCodeAgentUninstallPluginParams,
  ): Promise<ZCodePluginsUninstallResult> {
    const pluginId = params.pluginId
      ?? (params.pluginName && params.marketplace ? `${params.pluginName}@${params.marketplace}` : "");
    if (!pluginId) throw new Error("uninstallPlugin requires pluginId");
    const removeCache = params.removeCache !== false;
    return httpSend<ZCodePluginsUninstallResult>(
      `/api/plugins/installed/${encodePathSegment(pluginId)}`,
      "DELETE",
      undefined,
      { removeCache },
    );
  }

  async updatePlugin(params: ZCodeAgentUpdatePluginParams): Promise<ZCodePluginsInstallResult> {
    if (!params.pluginId) throw new Error("updatePlugin requires pluginId");
    return httpSend<ZCodePluginsInstallResult>(
      `/api/plugins/installed/${encodePathSegment(params.pluginId)}/update`,
      "POST",
    );
  }

  async restoreBuiltinPlugin(
    params: ZCodeAgentRestoreBuiltinPluginParams,
  ): Promise<ZCodePluginsRestoreBuiltinResult> {
    return httpSend<ZCodePluginsRestoreBuiltinResult>(
      `/api/plugins/installed/${encodePathSegment(params.pluginId)}/restore`,
      "POST",
    );
  }

  async configurePlugin(
    params: ZCodeAgentConfigurePluginParams,
  ): Promise<ZCodePluginsConfigureResult> {
    return httpSend<ZCodePluginsConfigureResult>(
      `/api/plugins/installed/${encodePathSegment(params.pluginId)}/configure`,
      "POST",
      { options: params.options ?? {}, clearOptionKeys: params.clearOptionKeys ?? [] },
    );
  }

  async resetPluginConfig(
    params: ZCodeAgentResetPluginConfigParams,
  ): Promise<ZCodePluginsConfigureResult> {
    return httpSend<ZCodePluginsConfigureResult>(
      `/api/plugins/installed/${encodePathSegment(params.pluginId)}/reset-config`,
      "POST",
    );
  }

  async validatePlugin(params: ZCodeAgentValidatePluginParams): Promise<ZCodePluginsValidateResult> {
    const source = params.source ?? (params.marketplace ? `${params.pluginName ?? ""}@${params.marketplace}` : "");
    if (!source) {
      return {
        ok: false,
        diagnostics: [
          { code: "plugin_marketplace_source_unsupported", message: "validatePlugin requires a source", severity: "error" },
        ],
        compatibility: { runnable: [], diagnosticOnly: [], unsupported: [] },
      };
    }
    return httpSend<ZCodePluginsValidateResult>("/api/plugins/marketplaces/validate", "POST", {
      source,
    });
  }

  async describePlugin(params: ZCodeAgentDescribePluginParams): Promise<ZCodePluginsDescribeResult> {
    return httpGet<ZCodePluginsDescribeResult>("/api/plugins/describe", {
      marketplace: params.marketplace,
      name: params.pluginName,
    });
  }

  async setPluginEnabled(
    params: ZCodeAgentSetPluginEnabledParams,
  ): Promise<ZCodePluginsSetEnabledResult> {
    return httpSend<ZCodePluginsSetEnabledResult>(
      `/api/plugins/installed/${encodePathSegment(params.pluginId)}/enabled`,
      "POST",
      { enabled: params.enabled },
    );
  }
}

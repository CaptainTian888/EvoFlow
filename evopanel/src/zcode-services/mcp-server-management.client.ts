// =============================================================================
// EvoFlow MCP Server Management Client
// Source: ZCode/packages/services/src/plugins/pluginManagement.client.ts
// Purpose: concrete IMcpServerManagementService implementation that talks to
//          the running EvoFlow Gateway (FastAPI sidecar). All HTTP calls are
//          relative to the current origin so the same code works in:
//            - Vite dev (proxied via /api -> 127.0.0.1:8070, see vite.config.js)
//            - Tauri-embedded webview (same /api served by sidecar via tauri://)
//            - packaged desktop build (same)
//
// Scope vs ZCode:
//   * `mcp-store` (evopanel/src/zcode-ui/store/mcpStore*.ts) already drives the
//     runtime config the agent uses. It is intentionally NOT changed here.
//   * This client is the *new* surface for code that imports
//     IMcpServerManagementService. Until such a caller is added the client is
//     unused, but wiring is in place and `getOverview()` round-trips against
//     the live gateway on `pnpm dev:tauri` (see mcp_external_smoke / dev).
// =============================================================================

import {
  EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID,
  type DefaultMcpServerMarketplace,
} from "@zcode/shared/mcp-marketplaces";
import type {
  AvailableMcpServerSummary,
  InstalledMcpServerSummary,
  McpMarketplaceSummary,
  McpServerScope,
  McpServersCapability,
  McpServersOverviewResult,
} from "@zcode/shared/mcp-server-types";
import type {
  IMcpServerManagementService,
  McpServerCatalogEntry,
  McpServerConfigureResult,
  McpServerDescribeResult,
  McpServerInstallResult,
  McpServerReferenceCatalogResult,
  McpServerRestoreBuiltinResult,
  McpServerSetEnabledResult,
  McpServerUninstallResult,
  McpServerValidateResult,
} from "./mcp-server-management.js";

// ---------------------------------------------------------------------------
// HTTP plumbing
// ---------------------------------------------------------------------------

const FETCH_TIMEOUT_MS = 15_000;

interface GatewayErrorPayload {
  detail?: string;
  message?: string;
}

class McpServerManagementError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(message: string, opts: { code?: string; status?: number } = {}) {
    super(message);
    this.name = "McpServerManagementError";
    this.code = opts.code ?? "mcp_server_management_error";
    this.status = opts.status ?? 0;
  }
}

async function gatewayFetch<T>(
  path: string,
  init: RequestInit & { parseJson?: boolean } = {},
): Promise<T> {
  const { parseJson = true, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(path, {
      ...rest,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(rest.method && rest.method !== "GET" ? { "Content-Type": "application/json" } : {}),
        ...rest.headers,
      },
    });
    if (!res.ok) {
      let payload: GatewayErrorPayload | null = null;
      try {
        payload = (await res.json()) as GatewayErrorPayload;
      } catch {
        // body is not JSON, fall through to status code only
      }
      const detail = payload?.detail ?? payload?.message ?? `${res.status} ${res.statusText}`;
      throw new McpServerManagementError(detail, {
        code: `http_${res.status}`,
        status: res.status,
      });
    }
    if (!parseJson) return undefined as T;
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof McpServerManagementError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new McpServerManagementError(`Gateway request timed out: ${path}`, {
        code: "timeout",
      });
    }
    const reason = err instanceof Error ? err.message : String(err);
    throw new McpServerManagementError(`Gateway request failed (${path}): ${reason}`, {
      code: "network",
    });
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Gateway payload types (subset of `cfg_repo` + `evoflow.mcp.status` shapes)
// ---------------------------------------------------------------------------

interface ConfigRepoMcpServerEntry {
  enabled?: boolean;
  type?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  description?: string;
}

interface ConfigRepoMcpListResponse {
  mcp_servers: Record<string, ConfigRepoMcpServerEntry>;
}

interface ObservabilityMcpToolInfo {
  name: string;
  full_name?: string;
  description?: string;
}

interface ObservabilityMcpServerEntry {
  name: string;
  enabled: boolean;
  transport?: string;
  load_status?: "disabled" | "pending" | "ready" | "error";
  error?: string | null;
  tool_count: number;
  tools: ObservabilityMcpToolInfo[];
  command?: string;
  args?: string[];
  url?: string;
}

interface ObservabilityMcpStatusResponse {
  config_path?: string;
  config_exists?: boolean;
  total_tools?: number;
  tool_counts?: Record<string, number>;
  servers: ObservabilityMcpServerEntry[];
}

// ---------------------------------------------------------------------------
// Cross-cutting projection helpers
// ---------------------------------------------------------------------------

const DEFAULT_MARKETPLACES: ReadonlyArray<DefaultMcpServerMarketplace> = (
  // Imported lazily so the bundler does not pull the const at module init when
  // a caller only needs the type. `DEFAULT_MCP_MARKETPLACES` is an array literal
  // on `mcp-marketplaces.ts`; we only need the id/source metadata for overview.
  [
    {
      id: EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID,
      source: "https://cdn.evoflow.ai/mcp/official/marketplace.json",
    } as DefaultMcpServerMarketplace,
  ]
);

function inferMarketplaceForName(name: string, installedMarketplaces: string[]): string {
  if (installedMarketplaces.includes(name)) return name;
  return EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID;
}

function buildMarketplaceSummaries(
  installedConfig: ConfigRepoMcpListResponse["mcp_servers"],
): McpMarketplaceSummary[] {
  // The EvoFlow gateway does not yet expose a /api/mcp/marketplaces endpoint
  // (openapi.json confirms it). We synthesize a single "official" marketplace
  // from the constant list and tag any non-official config keys as their own
  // ad-hoc marketplace (id == key) so callers see them in the overview.
  const seen = new Set<string>();
  const out: McpMarketplaceSummary[] = [];
  for (const def of DEFAULT_MARKETPLACES) {
    if (seen.has(def.id)) continue;
    seen.add(def.id);
    out.push({
      id: def.id,
      name: def.id,
      source: def.source,
      isOfficial: true,
      pluginCount: Object.keys(installedConfig).length,
      description:
        "Official EvoFlow MCP server marketplace (see zcode-shared/mcp-marketplaces.ts).",
    });
  }
  for (const key of Object.keys(installedConfig)) {
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      id: key,
      name: key,
      source: "local",
      isOfficial: false,
      pluginCount: 1,
      description: "Locally registered MCP server (cfg_repo).",
    });
  }
  return out;
}

function buildInstalledServers(
  config: ConfigRepoMcpListResponse["mcp_servers"],
  status: ObservabilityMcpStatusResponse["servers"],
  scope: McpServerScope,
): InstalledMcpServerSummary[] {
  const statusByName = new Map<string, ObservabilityMcpServerEntry>();
  for (const s of status ?? []) statusByName.set(s.name, s);

  const marketplaces = Array.from(
    new Set([EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID, ...Object.keys(config)]),
  );

  const summaries: InstalledMcpServerSummary[] = [];
  for (const [name, entry] of Object.entries(config ?? {})) {
    const runtime = statusByName.get(name);
    summaries.push({
      id: name,
      name,
      marketplace: inferMarketplaceForName(name, marketplaces),
      enabled: entry.enabled ?? runtime?.enabled ?? true,
      scope,
      description: entry.description ?? "",
      version: undefined,
      componentTypes: ["mcp"],
      // `nativeScope` and `installPath` are intentionally omitted; the
      // gateway endpoint does not surface them and `mcpStore` already tracks
      // user-level vs workspace-level via `projectPath`.
    });
  }
  return summaries;
}

function buildAvailableServers(
  installedNames: Set<string>,
  marketplaces: McpMarketplaceSummary[],
): AvailableMcpServerSummary[] {
  // The gateway's official market list is held by the Rust `mcp_market_search`
  // tauri command; we surface a stable placeholder that names the bundled
  // markers so the UI knows `availableServers` is non-empty. Detailed rows
  // come from a future /api/mcp/market/search call once a gateway token helper
  // is wired in.
  return marketplaces.map((m) => ({
    id: m.id,
    name: m.name,
    marketplace: m.id,
    description: m.description,
    installed: installedNames.has(m.id),
    componentTypes: ["mcp"],
  }));
}

function buildCapability(): McpServersCapability {
  // The desktop runtime is the only host that can manage MCP processes, but
  // we do not gate this client on Tauri here: the same gateway is reachable
  // from Vite dev. Future work can flip this off when running in pure web.
  return { supported: true };
}

// ---------------------------------------------------------------------------
// Client implementation
// ---------------------------------------------------------------------------

export interface McpServerManagementClientOptions {
  /** Override the base URL. Defaults to the current origin (works with Vite proxy). */
  baseUrl?: string;
}

export class EvoFlowMcpServerManagementClient implements IMcpServerManagementService {
  private readonly baseUrl: string;

  constructor(opts: McpServerManagementClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? "").replace(/\/+$/, "");
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  // ---- read paths ---------------------------------------------------------

  async listServers(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    scope?: McpServerScope;
  }): Promise<InstalledMcpServerSummary[]> {
    const [config, status] = await Promise.all([
      gatewayFetch<ConfigRepoMcpListResponse>(this.url("/api/config/mcp-servers")),
      gatewayFetch<ObservabilityMcpStatusResponse>(
        this.url("/api/observability/mcp-status"),
      ).catch(() => ({ servers: [] } as ObservabilityMcpStatusResponse)),
    ]);
    return buildInstalledServers(config.mcp_servers ?? {}, status.servers, "user");
  }

  async getServersOverview(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    scope?: McpServerScope;
  }): Promise<McpServersOverviewResult> {
    const [config, status] = await Promise.all([
      gatewayFetch<ConfigRepoMcpListResponse>(this.url("/api/config/mcp-servers")),
      gatewayFetch<ObservabilityMcpStatusResponse>(
        this.url("/api/observability/mcp-status"),
      ).catch(() => ({ servers: [] } as ObservabilityMcpStatusResponse)),
    ]);
    const marketplaces = buildMarketplaceSummaries(config.mcp_servers ?? {});
    const installedServers = buildInstalledServers(
      config.mcp_servers ?? {},
      status.servers,
      "user",
    );
    const availableServers = buildAvailableServers(
      new Set(installedServers.map((s) => s.name)),
      marketplaces,
    );
    return {
      marketplaces,
      availableServers,
      installedServers,
      capability: buildCapability(),
    };
  }

  async getServerReferenceCatalog(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    sessionId?: string;
  }): Promise<McpServerReferenceCatalogResult> {
    const overview = await this.getServersOverview({});
    const servers: McpServerCatalogEntry[] = [
      ...overview.installedServers.map((s) => ({
        id: s.id,
        name: s.name,
        marketplace: s.marketplace,
        description: s.description,
      })),
      ...overview.availableServers
        .filter((s) => !overview.installedServers.some((i) => i.name === s.name))
        .map((s) => ({
          id: s.id,
          name: s.name,
          marketplace: s.marketplace,
          description: s.description,
        })),
    ];
    return { servers, total: servers.length };
  }

  async resolveSuggestedServerReference(params: {
    marketplace?: string;
    slug?: string;
  }): Promise<McpServerCatalogEntry | null> {
    if (!params.slug) return null;
    const catalog = await this.getServerReferenceCatalog({});
    return (
      catalog.servers.find(
        (s) => s.id === params.slug || s.name === params.slug,
      ) ?? null
    );
  }

  // ---- marketplace CRUD (no-op against current gateway) -------------------

  async addMarketplace(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    source: string;
    scope?: McpServerScope;
  }): Promise<void> {
    // The gateway does not expose a marketplace registry endpoint; marketplace
    // sources are baked into the bundled official list. Fail loudly so callers
    // know the registry is read-only.
    throw new McpServerManagementError(
      "EvoFlow gateway does not support runtime marketplace registration; marketplaces are bundled.",
      { code: "not_implemented" },
    );
  }

  async removeMarketplace(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    marketplace: string;
  }): Promise<void> {
    throw new McpServerManagementError(
      "EvoFlow gateway does not support runtime marketplace removal; marketplaces are bundled.",
      { code: "not_implemented" },
    );
  }

  async updateMarketplace(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    marketplace?: string;
  }): Promise<void> {
    // No-op: bundled marketplaces cannot be updated through this client.
    return;
  }

  // ---- install / uninstall / update ---------------------------------------

  async installServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerInstallResult> {
    // Pre-installed MCP servers are configured through `cfg_repo.upsert_mcp_server`
    // (PUT /api/config/mcp-servers/{name}). For marketplace-only items we cannot
    // fetch install metadata, so the caller must provide a configuration via
    // `configureServer` afterwards. This method acts as a "create empty entry"
    // so downstream config flows can fill it in.
    try {
      await gatewayFetch(this.url(`/api/config/mcp-servers/${encodeURIComponent(params.serverName)}`), {
        method: "PUT",
        body: JSON.stringify({ enabled: true, type: "stdio" }),
      });
      return { success: true, serverName: params.serverName };
    } catch (err) {
      return {
        success: false,
        serverName: params.serverName,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }

  async uninstallServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerUninstallResult> {
    try {
      await gatewayFetch(
        this.url(`/api/config/mcp-servers/${encodeURIComponent(params.serverName)}`),
        { method: "DELETE" },
      );
      return { success: true, serverName: params.serverName };
    } catch (err) {
      return {
        success: false,
        serverName: params.serverName,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }

  async updateServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerInstallResult> {
    return this.installServer(params);
  }

  async cancelServerOperation(_params: { operationId: string }) {
    // All gateway operations are synchronous from the caller's perspective;
    // there is no operation to cancel. Return success to keep the contract
    // boring until an async install flow lands.
    return { success: true, operationId: _params.operationId };
  }

  async restoreBuiltinServer(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    scope?: McpServerScope;
  }): Promise<McpServerRestoreBuiltinResult> {
    return {
      success: false,
      serverName: _params.serverName,
      error: "restoreBuiltinServer is not supported against the EvoFlow gateway",
    };
  }

  // ---- per-server configuration -------------------------------------------

  async configureServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
    options: Record<string, string | number | boolean>;
  }): Promise<McpServerConfigureResult> {
    try {
      const current = await gatewayFetch<ConfigRepoMcpListResponse>(
        this.url("/api/config/mcp-servers"),
      );
      const existing = current.mcp_servers?.[params.serverName] ?? {};
      const next: ConfigRepoMcpServerEntry = {
        ...existing,
        enabled:
          typeof params.options.enabled === "boolean"
            ? (params.options.enabled as boolean)
            : (existing.enabled ?? true),
        description:
          typeof params.options.description === "string"
            ? (params.options.description as string)
            : existing.description,
      };
      await gatewayFetch(
        this.url(`/api/config/mcp-servers/${encodeURIComponent(params.serverName)}`),
        { method: "PUT", body: JSON.stringify(next) },
      );
      return {
        success: true,
        serverName: params.serverName,
        configuredOptions: params.options,
      };
    } catch (err) {
      return {
        success: false,
        serverName: params.serverName,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }

  async resetServerConfig(_params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    scope?: McpServerScope;
  }): Promise<McpServerConfigureResult> {
    try {
      await gatewayFetch(
        this.url(`/api/config/mcp-servers/${encodeURIComponent(_params.serverName)}`),
        { method: "DELETE" },
      );
      return { success: true, serverName: _params.serverName };
    } catch (err) {
      return {
        success: false,
        serverName: _params.serverName,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }

  async validateServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerValidateResult> {
    try {
      const status = await gatewayFetch<ObservabilityMcpStatusResponse>(
        this.url("/api/observability/mcp-status"),
      );
      const entry = status.servers.find((s) => s.name === params.serverName);
      if (!entry) {
        return {
          valid: false,
          errors: [`MCP server "${params.serverName}" is not registered in cfg_repo`],
        };
      }
      const errors: string[] = [];
      const warnings: string[] = [];
      if (entry.load_status === "error" && entry.error) errors.push(entry.error);
      if (!entry.enabled) warnings.push("MCP server is disabled");
      if (entry.load_status === "pending") warnings.push("MCP server is still initializing");
      return { valid: errors.length === 0, errors, warnings };
    } catch (err) {
      return {
        valid: false,
        errors: [err instanceof Error ? err.message : String(err)],
      };
    }
  }

  async describeServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerDescribeResult> {
    try {
      const [config, status] = await Promise.all([
        gatewayFetch<ConfigRepoMcpListResponse>(this.url("/api/config/mcp-servers")),
        gatewayFetch<ObservabilityMcpStatusResponse>(this.url("/api/observability/mcp-status")),
      ]);
      const entry = config.mcp_servers?.[params.serverName];
      const runtime = status.servers.find((s) => s.name === params.serverName);
      if (!entry) {
        return {
          name: params.serverName,
          marketplace: params.marketplace,
          error: `MCP server "${params.serverName}" is not registered`,
        };
      }
      return {
        name: params.serverName,
        marketplace: params.marketplace,
        description: entry.description,
        installCommand: entry.command,
        capabilities: runtime?.tools.map((t) => t.name),
        categories: [],
        tags: [],
      };
    } catch (err) {
      return {
        name: params.serverName,
        marketplace: params.marketplace,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }

  async setServerEnabled(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
    enabled: boolean;
  }): Promise<McpServerSetEnabledResult> {
    try {
      const config = await gatewayFetch<ConfigRepoMcpListResponse>(
        this.url("/api/config/mcp-servers"),
      );
      const existing = config.mcp_servers?.[params.serverName] ?? {};
      await gatewayFetch(
        this.url(`/api/config/mcp-servers/${encodeURIComponent(params.serverName)}`),
        { method: "PUT", body: JSON.stringify({ ...existing, enabled: params.enabled }) },
      );
      return {
        success: true,
        serverName: params.serverName,
        enabled: params.enabled,
      };
    } catch (err) {
      return {
        success: false,
        serverName: params.serverName,
        enabled: params.enabled,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }
}

// ---------------------------------------------------------------------------
// Sync export/import — the ZCode `IMcpServerManagementService` does not carry
// sync methods directly; sync lives in `IMcpSyncService` (`./mcp-sync`).
// Callers that need a sync payload should derive it from `getServersOverview()`.
// This class is intentionally a thin alias: the gateway has no archive
// endpoint, and pretending otherwise would be a lie. It exists so service
// registries that need a "default" implementation have a typed handle.
// ---------------------------------------------------------------------------

export class EvoFlowMcpServerManagementClientWithSync extends EvoFlowMcpServerManagementClient {
  // Reserved for future gateway-backed sync. Today, `archiveExport` / `archiveImport`
  // are exposed via `IMcpSyncService` (see `zcode-services/mcp-sync`).
}

export { McpServerManagementError };

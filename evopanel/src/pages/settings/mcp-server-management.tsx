/**
 * EvoFlow 设置中心 — MCP 服务器管理 Tab
 *
 * 原样引用 ZCode 的 <McpSettingsSection> React 组件,
 * 通过 React 18 createRoot 桥接到 EvoFlow vanilla JS hub.js.
 *
 * Provider 树:
 *   - TabStoreProvider     → zustand store, module load 即就绪
 *   - PlatformProvider     → 显式 IPlatformService (40+ 可选方法占位)
 *   - ServiceProvider      → 真实 3 个 service:
 *     · mcpSyncService        = 读 /api/config/mcp-servers + /api/observability/mcp-status
 *     · pluginManagementService = EvoFlow 官方市场 + 8 个预设 availablePlugins
 *     · settingsSyncService   = no-op (EvoFlow 不经 ZCode settings sync)
 *
 * 数据加载:
 *   useEnsureWorkspaceMcpLoaded 内部会自动:
 *     1. setMcpStoreDirectoryService(mcpSyncService)
 *     2. useMcpStore.ensureLoadedForWorkspace(workspacePath)
 *   → mcpSyncService.loadMcpFromUserDirectory() 返回 NativeMcpServerRecord[]
 *   → mcpStore.servers 重组, 组件渲染「已装」
 *
 * Marketplace:
 *   usePluginManagementStore 通过 pluginManagementService.getPluginsOverview() 拉
 *   marketplaces + availablePlugins, 「未安装」列表由此渲染
 *
 * 挂载约定(与 hub.js ensurePanelMounted 对齐):
 *   export function mountMcpServerManagementInto(container, opts)
 *   export function cleanup()
 */

import { createElement, type ReactElement, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { TabStoreProvider } from "@/store/TabStoreProvider.js";
import { PlatformProvider, usePlatform } from "@/hooks/usePlatform.js";
import { ServiceProvider, useServices } from "@/hooks/useServices.js";
import { ZCodeIntlProvider } from "@/i18n/IntlProvider.js";
import { TooltipProvider } from "@/components/ui/tooltip.js";
import { useMcpStore, setMcpStoreDirectoryService } from "@/store/mcpStore.js";
import { usePluginManagementStore } from "@/store/pluginManagementStore.js";
import { McpSettingsSection } from "@/settings/McpSettingsSection.js";
import type { IPlatformService } from "@zcode/shared";
import type { IServiceAccessor } from "@zcode/services";
import type {
  IMcpSyncService,
  IPluginManagementService,
  ISettingsSyncService,
} from "@zcode/services";
import { EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID } from "@zcode/shared/mcp-marketplaces";
import { EvoFlowMcpServerManagementClient } from "../../zcode-services/mcp-server-management.client.js";
import { gatewayProxy } from "../../lib/tauri-api.js";
import "@/styles-bridge.css";

// ---------------------------------------------------------------------------
// 0. 单例 client —— 共享 HTTP 状态
// ---------------------------------------------------------------------------

const client = new EvoFlowMcpServerManagementClient();

// ---------------------------------------------------------------------------
// 1. mcpSyncService 真实实现 —— 调 EvoFlow Gateway HTTP
// ---------------------------------------------------------------------------

interface GatewayMcpConfigServer {
  name: string;
  enabled: boolean;
  transport: string;
  command: string;
  args: string[];
  url?: string;
  headers?: Record<string, string>;
  env?: Record<string, string>;
  load_status?: string;
  error?: string | null;
  tool_count?: number;
  tools?: { name: string; description?: string }[];
}

interface GatewayMcpListResponse {
  config_path?: string;
  mcp_servers?: Record<string, GatewayMcpConfigServer>;
  servers?: GatewayMcpConfigServer[];
  total_tools?: number;
}

function toNativeMcpServerRecord(name: string, s: GatewayMcpConfigServer) {
  const config: Record<string, unknown> = {};
  if (s.transport === "stdio") {
    if (s.command) config.command = s.command;
    if (s.args?.length) config.args = s.args;
    if (s.env) config.env = s.env;
  } else if (s.transport === "http" || s.transport === "streamableHttp") {
    if (s.url) config.url = s.url;
    if (s.headers) config.headers = s.headers;
  } else if (s.command) {
    config.command = s.command;
    if (s.args?.length) config.args = s.args;
  }
  if (s.transport) config.type = s.transport;

  return {
    source: "zcodeagentmcp" as const,
    scope: "user" as const,
    name,
    config,
    enabled: s.enabled !== false,
  };
}

async function gatewayGetJson<T>(url: string): Promise<T> {
  // 桌面端走 gatewayProxy，避免裸 fetch 相对 /api 拿到 SPA HTML。
  return (await gatewayProxy("GET", url)) as T;
}

async function gatewaySendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return (await gatewayProxy(method, url, body ?? null)) as T;
}

function createEvoflowMcpSyncService(): IMcpSyncService {
  // 整个 service 强转 as IMcpSyncService — ZCode 的 McpSync schema 与 EvoFlow
  // gateway 形态不严格匹配, 我们只覆盖 load/list/save 三条主线, 其余 noop
  // 由 IPluginManagementService 一样的"as unknown as"模式绕开.
  return {
    async loadMcpFromUserDirectory(_req: unknown) {
      const resp = await gatewayGetJson<GatewayMcpListResponse>("/api/config/mcp-servers");
      const map = resp.mcp_servers ?? {};
      const servers = Object.entries(map).map(([name, s]) =>
        toNativeMcpServerRecord(name, s as GatewayMcpConfigServer),
      );
      return { servers };
    },

    async listWorkspaceMcpServerStatuses(_params: unknown) {
      try {
        const status = await gatewayGetJson<GatewayMcpListResponse>(
          "/api/observability/mcp-status",
        );
        return {
          mcpServers: (status.servers ?? []).map((s) => ({
            name: s.name,
            enabled: s.enabled,
            status: s.load_status,
            toolCount: s.tool_count ?? 0,
            tools: s.tools ?? [],
            error: s.error ?? null,
          })),
          totalTools: status.total_tools ?? 0,
        };
      } catch {
        return { mcpServers: [], totalTools: 0 };
      }
    },

    async saveMcpToUserDirectory(payload: unknown) {
      // payload: { servers: Record<string, McpServerConfig>, projectPath? }
      const servers = (payload as unknown as { servers?: Record<string, Record<string, unknown>> }).servers ?? {};
      for (const [name, cfg] of Object.entries(servers)) {
        const transport = (cfg.type as string) ?? "stdio";
        const body: Record<string, unknown> = { name, enabled: true, transport };
        if (transport === "stdio") {
          if (typeof cfg.command === "string") body.command = cfg.command;
          if (Array.isArray(cfg.args)) body.args = cfg.args;
          if (cfg.env) body.env = cfg.env;
        } else {
          if (typeof cfg.url === "string") body.url = cfg.url;
          if (cfg.headers) body.headers = cfg.headers;
        }
        await gatewaySendJson(
          `/api/config/mcp-servers/${encodeURIComponent(name)}`,
          "PUT",
          body,
        );
      }
    },

    async listLocalUserMcpCandidates() {
      const overview = await client.getServersOverview({});
      const r = {
        candidates: overview.availableServers.map((s) => ({
          name: s.name,
          marketplace: s.marketplace,
          sourcePath: "",
        })),
      };
      return r as never;
    },

    async listRemoteUserMcpStatuses() {
      return { statuses: {} } as never;
    },

    async exportMcpServers() {
      return { servers: [] } as never;
    },

    async checkRemoteUserMcpWriteAccess() {
      return { allowed: false } as never;
    },

    async importMcpServers(_params: {
      servers: unknown[];
      localHomeDir: string;
      localWorkspacePath?: string;
      remoteWorkspacePath?: string;
      overwrite?: false;
    }) {
      return { imported: 0, skipped: 0 } as never;
    },
  } as unknown as IMcpSyncService;
}

// ---------------------------------------------------------------------------
// 2. pluginManagementService —— EvoFlow 官方市场 + 8 个预设
// ---------------------------------------------------------------------------

const EVOFLOW_MARKETPLACE_PRESET: Array<{
  name: string;
  description: string;
  command: string;
  args: string[];
  env?: Record<string, string>;
}> = [
  {
    name: "filesystem",
    description: "提供受限的文件系统访问：读写工作目录内文件、列举目录、搜索文本。",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."],
  },
  {
    name: "fetch",
    description: "从 URL 抓取网页内容并转成可消费的 Markdown / 文本。",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-fetch"],
  },
  {
    name: "github",
    description: "通过 GitHub API 读仓库、Issues、PR、文件。需要在环境里设 GITHUB_TOKEN。",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-github"],
    env: { GITHUB_TOKEN: "" },
  },
  {
    name: "sqlite",
    description: "在本地 SQLite 文件上执行 SQL 查询。",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "./.evoflow.sqlite"],
  },
  {
    name: "puppeteer",
    description: "用无头 Chromium 抓取动态网页、生成截图。",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-puppeteer"],
  },
  {
    name: "playwright",
    description: "用 Playwright 自动化浏览器、跨页面操作。",
    command: "npx",
    args: ["-y", "@playwright/mcp@latest"],
  },
  {
    name: "sequential-thinking",
    description: "链式思考辅助：分步拆解复杂问题再合并结论。",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-sequential-thinking"],
  },
  {
    name: "memory",
    description: "知识图谱：跨会话保留实体 / 关系记忆。",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-memory"],
  },
];

function createEvoflowPluginManagementService(): IPluginManagementService {
  // 大部分方法是 install/uninstall/configure 链路, EvoFlow 通过 HTTP PUT/DELETE
  // 直接调 /api/config/mcp-servers/{name} 完成; 不严格匹配 ZCode 返回 schema
  // 用 as unknown as 让所有方法都 "存在".
  const noop = async () => undefined;

  const fetchOverview = async () => {
    const overview = await client.getServersOverview({});
    return {
      marketplaces: [
        {
          id: EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID,
          name: "EvoFlow 官方市场",
          description: "EvoFlow 预置的 8 个常用 MCP 服务器。",
          enabled: true,
          sourceKind: "official",
          sourceUrl: "https://evoflow.local/marketplace/official",
          pluginCount: EVOFLOW_MARKETPLACE_PRESET.length,
        },
      ],
      availablePlugins: EVOFLOW_MARKETPLACE_PRESET.map((p) => ({
        id: `${EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID}:${p.name}`,
        name: p.name,
        marketplace: EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID,
        description: p.description,
        version: "1.0.0",
        installed: false,
        componentTypes: ["mcp-server"],
      })),
      installedPlugins: overview.installedServers.map((s) => ({
        id: `${s.marketplace}:${s.name}`,
        name: s.name,
        marketplace: s.marketplace,
        description: s.description,
        version: s.version,
        enabled: s.enabled,
        scope: "user" as const,
        installPath: "",
        installedAt: "",
        componentTypes: ["mcp-server"],
      })),
      restorableBuiltins: [],
      diagnostics: [],
      capability: { supported: true, reason: null, features: ["install", "uninstall"] },
    };
  };

  return {
    getPluginsOverview: async () => {
      return fetchOverview();
    },

    listPlugins: async (_params: unknown) => {
      const overview = await fetchOverview();
      return {
        plugins: overview.installedPlugins,
        diagnostics: [],
      } as never;
    },
    getPluginReferenceCatalog: async (_params: unknown) => {
      const overview = await fetchOverview();
      const refEntries = [
        ...overview.installedPlugins,
        ...overview.availablePlugins,
      ].map((p) => ({
        id: p.id,
        name: p.name,
        marketplace: p.marketplace,
        description: p.description,
      }));
      return { servers: refEntries, total: refEntries.length } as never;
    },
    resolveSuggestedPluginReference: async (
      params: { marketplace?: string; slug?: string },
    ) => {
      if (!params.slug) return null;
      return {
        id: `${params.marketplace ?? EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID}:${params.slug}`,
        name: params.slug,
        marketplace: params.marketplace ?? EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID,
      } as never;
    },
    onDynamicPluginOperationProgress: (() => {
      // Event<...> 在 runtime 是 Event 抽象类, 不可直接 new. 返回一个
      // 形似 Event 的对象, dispose() 即可.
      const e = {
        dispose: () => {},
        [Symbol.dispose]: () => {},
      };
      return () => e as never;
    })(),
    addPluginMarketplace: noop,
    removePluginMarketplace: noop,
    updatePluginMarketplace: noop,

    installPlugin: async (params: { serverName: string }) => {
      const preset = EVOFLOW_MARKETPLACE_PRESET.find((p) => p.name === params.serverName);
      if (!preset) {
        return { success: false, error: `未知 MCP 服务器：${params.serverName}` };
      }
      await gatewaySendJson(
        `/api/config/mcp-servers/${encodeURIComponent(params.serverName)}`,
        "PUT",
        {
          name: params.serverName,
          enabled: true,
          transport: "stdio",
          command: preset.command,
          args: preset.args,
          env: preset.env ?? {},
        },
      );
      return { success: true };
    },

    uninstallPlugin: async (params: { serverName: string }) => {
      await gatewaySendJson(
        `/api/config/mcp-servers/${encodeURIComponent(params.serverName)}`,
        "DELETE",
      );
      return { success: true };
    },

    setPluginEnabled: async (params: { serverName: string; enabled: boolean }) => {
      await gatewaySendJson(
        `/api/config/mcp-servers/${encodeURIComponent(params.serverName)}/enabled`,
        "PUT",
        { enabled: params.enabled },
      );
      return { success: true };
    },

    cancelPluginOperation: noop,
    updatePlugin: noop,
    restoreBuiltinPlugin: noop,
    configurePlugin: noop,
    resetPluginConfig: noop,
    validatePlugin: noop,
    describePlugin: noop,
  } as unknown as IPluginManagementService;
}

// ---------------------------------------------------------------------------
// 3. settingsSyncService — no-op
// ---------------------------------------------------------------------------

function createEvoflowSettingsSyncService(): ISettingsSyncService {
  const noop = async () => ({});
  return {
    pullSettings: noop,
    pushSettings: noop,
    listPendingChanges: noop,
  } as unknown as ISettingsSyncService;
}

// ---------------------------------------------------------------------------
// 4. Service 工厂 + Provider
// ---------------------------------------------------------------------------

function createEvoflowServiceAccessor(): IServiceAccessor {
  return {
    mcpSyncService: createEvoflowMcpSyncService(),
    pluginManagementService: createEvoflowPluginManagementService(),
    settingsSyncService: createEvoflowSettingsSyncService(),
  } as unknown as IServiceAccessor;
}

const stubPlatform: IPlatformService = {
  selectDirectory: async () => null,
  selectFile: async () => null,
  selectFiles: async () => [],
  activateOrSetWorkspace: async () => ({ activated: false }),
  onRemoteConnectionLog: () => () => {},
  onRemoteSessionClosed: () => () => {},
  onBotRemoteWorkspaceReconnected: () => () => {},
  connectRemote: async () => ({ success: false, error: "stub" }),
} as unknown as IPlatformService;

// ---------------------------------------------------------------------------
// Internal React app
// ---------------------------------------------------------------------------

function EvoflowMcpApp(): ReactElement {
  const services = createEvoflowServiceAccessor();

  // EvoFlow 启动时没注入 mcpPlatformService / mcpDirectoryService,
  // useEnsureWorkspaceMcpLoaded 因为 workspace services 不在而不会触发.
  // 这里在 mount 后主动灌入 + 调 store 的 ensure/initialize, 拉真实数据.
  useEffect(() => {
    const mcpSync = services.mcpSyncService;
    const pluginSvc = services.pluginManagementService;

    setMcpStoreDirectoryService(mcpSync as never);
    void useMcpStore
      .getState()
      .loadMcpFromUserDirectory(mcpSync as never, undefined);

    void usePluginManagementStore
      .getState()
      .initialize({
        workspacePath: "",
        workspaceIdentity: undefined,
        configScope: "user",
        pluginService: pluginSvc as never,
      });

    return () => {
      setMcpStoreDirectoryService(null);
    };
  }, [services]);

  const settingsSection = createElement(McpSettingsSection, {
    workspacePath: undefined,
    workspaceIdentity: undefined,
    remoteSessionId: undefined,
    remoteTarget: undefined,
    localWorkspacePath: undefined,
    scopeFilter: "user",
    parentScopeKey: "",
    workspaceTabs: [],
    searchQuery: "",
    onVisibleCountChange: undefined,
    onEditorOpenChange: undefined,
    onFormScopeKeyChange: undefined,
    onOpenPluginStore: undefined,
    showMarketplaceBreadcrumb: false,
  });

  const withServices = createElement(
    ServiceProvider,
    { services, children: settingsSection },
  );

  return createElement(PlatformProvider, {
    platform: stubPlatform,
    children: createElement(ZCodeIntlProvider, {
      initialLocale: "zh-CN",
      children: createElement(TooltipProvider, null, withServices),
    }),
  });
}

// ---------------------------------------------------------------------------
// Mount / cleanup
// ---------------------------------------------------------------------------

const _roots = new Map<HTMLElement, Root>();

export function mountMcpServerManagementInto(
  container: HTMLElement,
  _opts: { initialScopeFilter?: "user" | "workspace" } = {},
): void {
  cleanup();
  container.innerHTML = "";

  const host = document.createElement("div");
  host.className = "zcode-bridge-root";
  host.style.cssText = "width:100%;min-height:400px;color-scheme:light;";
  container.appendChild(host);

  const root = createRoot(host);
  _roots.set(container, root);

  root.render(
    createElement(TabStoreProvider, { children: createElement(EvoflowMcpApp) }),
  );
}

export function cleanup(): void {
  for (const [container, root] of _roots) {
    try {
      root.unmount();
    } catch {
      /* ignore */
    }
    if (container.isConnected) container.innerHTML = "";
  }
  _roots.clear();
}

void usePlatform;
void useServices;

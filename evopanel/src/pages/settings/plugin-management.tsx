/**
 * EvoFlow 设置中心 — 插件市场 Tab（ZCode PluginsSection 原版挂载）
 *
 * 原样引用 ZCode 的 <PluginsSection>（插件列表 + 插件商店；MCP/技能
 * tab 暂藏，待迁移完成再开放）与 <PluginStorePage>（插件市场整页），通过
 * createRoot 桥接到 EvoFlow vanilla JS hub.js。
 *
 * 数据链路：
 *   pluginManagementService = EvoflowPluginManagementClient → Gateway
 *   /api/plugins/*（Python 端口自 ZCode CLI 插件适配器，存储布局与
 *   ZCode 逐字节兼容：known_marketplaces.json / installed_plugins.json /
 *   marketplaces/<id>/marketplace.json / cache/<marketplace>/<name>/<version>）
 *   mcpSyncService          = 共享工厂（evoflow-bridge-services.ts）
 *
 * 挂载约定（与 hub.js ensurePanelMounted 对齐）：
 *   export function mountPluginManagementInto(container)
 *   export function cleanup()
 */

import { createElement, useEffect, useState, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { TabStoreProvider } from "@/store/TabStoreProvider.js";
import { PlatformProvider } from "@/hooks/usePlatform.js";
import { ServiceProvider } from "@/hooks/useServices.js";
import { ZCodeIntlProvider } from "@/i18n/IntlProvider.js";
import { TooltipProvider } from "@/components/ui/tooltip.js";
import { useMcpStore, setMcpStoreDirectoryService } from "@/store/mcpStore.js";
import { usePluginManagementStore } from "@/store/pluginManagementStore.js";
import { PluginsSection } from "@/settings/PluginsSection.js";
import { PluginStorePage } from "@/settings/PluginStorePage.js";
import "@/styles-bridge.css";
import type { IServiceAccessor } from "@zcode/services";
import { EvoflowPluginManagementClient } from "../../zcode-services/plugins/pluginManagement.client.js";
import {
  createEvoflowMcpSyncService,
  createEvoflowSettingsSyncService,
  evoflowStubPlatform,
} from "./evoflow-bridge-services.js";

// 桥接页没有真实 workspace，给插件服务解析一个稳定的合成标识。
const BRIDGE_WORKSPACE_PATH = "evoflow://plugins";

// ---------------------------------------------------------------------------
// 单例 client —— 共享 HTTP 状态
// ---------------------------------------------------------------------------

const pluginClient = new EvoflowPluginManagementClient();
const mcpSyncService = createEvoflowMcpSyncService();

function createEvoflowServiceAccessor(): IServiceAccessor {
  return {
    pluginManagementService: pluginClient,
    mcpSyncService,
    settingsSyncService: createEvoflowSettingsSyncService(),
    // PluginStorePage / PluginsSection 会从 accessor 取这些服务；
    // 当前组件树未实际调用其方法，提供空实现防止 undefined 解引用。
    clientConfigService: {
      getSnapshot: async () => ({ pluginStoreOrder: null }),
    },
    // Skills tab（PluginsSection 内嵌）只读列表；EvoFlow 技能管理在原生页提供。
    skillsService: {
      list: async () => ({ skills: [], capability: null, diagnostics: [] }),
      setEnabled: async () => ({}),
      deleteSkill: async () => ({}),
    },
    zcodeSessionService: {},
  } as unknown as IServiceAccessor;
}

// ---------------------------------------------------------------------------
// Internal React app
// ---------------------------------------------------------------------------

function EvoflowPluginApp(): ReactElement {
  const services = createEvoflowServiceAccessor();
  const [storeOpen, setStoreOpen] = useState(false);

  useEffect(() => {
    // MCP tab（PluginsSection 内嵌）需要 mcpStore 预载，与 MCP 桥接页一致。
    setMcpStoreDirectoryService(mcpSyncService as never);
    void useMcpStore
      .getState()
      .loadMcpFromUserDirectory(mcpSyncService as never, undefined);

    void usePluginManagementStore.getState().initialize({
      workspacePath: BRIDGE_WORKSPACE_PATH,
      workspaceIdentity: undefined,
      configScope: "user",
      pluginService: pluginClient as never,
    });

    return () => {
      setMcpStoreDirectoryService(null);
    };
  }, [services]);

  const content = storeOpen
    ? createElement(PluginStorePage, {
        workspacePath: BRIDGE_WORKSPACE_PATH,
        onManageInstalled: () => setStoreOpen(false),
      })
    : createElement(PluginsSection, {
        isDesktop: false,
        initialTab: "plugins",
        initialScopeKey: "user",
        mode: "plugin",
        workspacePath: BRIDGE_WORKSPACE_PATH,
        onOpenPluginStore: () => setStoreOpen(true),
        showMarketplaceBreadcrumb: false,
      });

  const withServices = createElement(
    ServiceProvider,
    { services, children: content },
  );

  return createElement(PlatformProvider, {
    platform: evoflowStubPlatform,
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

export function mountPluginManagementInto(
  container: HTMLElement,
  _opts: { initialTab?: "plugins" | "mcps" | "skills" } = {},
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
    createElement(TabStoreProvider, { children: createElement(EvoflowPluginApp) }),
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

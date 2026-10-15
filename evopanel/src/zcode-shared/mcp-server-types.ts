// =============================================================================
// ZCode Plugin Types - Ported to EvoFlow MCP Server Management
// Source: ZCode/packages/shared/src/plugin-types.ts
// Changes: Plugin → MCP Server, plugin → mcp-server
// =============================================================================

export interface McpMarketplaceSummary {
  id: string;
  name: string;
  source: string;
  installLocation?: string;
  lastUpdated?: string;
  pluginCount: number;
  description?: string;
  isOfficial: boolean;
}

export type McpComponentType = "agent" | "command" | "skill" | "hook" | "mcp" | "lsp";

export type McpServerScope = "workspace" | "user";

export interface McpHookDetail {
  args?: string[];
  async?: boolean;
  command: string;
  event: string;
  matcher?: string;
  runnable: boolean;
  shell?: true | string;
  sourcePath: string;
  statusMessage?: string;
  timeout?: number;
  timeoutMs?: number;
  type: "command" | "process";
}

export interface AvailableMcpServerSummary {
  id: string;
  name: string;
  marketplace: string;
  description?: string;
  version?: string;
  installed: boolean;
  componentTypes?: McpComponentType[];
}

export interface InstalledMcpServerSummary {
  id: string;
  name: string;
  marketplace: string;
  description?: string;
  version?: string;
  enabled: boolean;
  scope: McpServerScope;
  installPath?: string;
  nativeScope?: "user" | "project" | "local";
  projectPath?: string;
  installedAt?: string;
  componentTypes?: McpComponentType[];
  hookDetails?: McpHookDetail[];
}

export interface McpServersCapability {
  supported: boolean;
  reason?: "desktop_only" | "missing_cli";
}

export interface McpServersOverviewResult {
  marketplaces: McpMarketplaceSummary[];
  availableServers: AvailableMcpServerSummary[];
  installedServers: InstalledMcpServerSummary[];
  capability: McpServersCapability;
}

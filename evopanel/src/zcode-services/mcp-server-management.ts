// =============================================================================
// ZCode Plugin Management Service - Ported to EvoFlow MCP Server Management
// Source: ZCode/packages/services/src/plugins/pluginManagement.ts
// Changes: Plugin → MCP Server
// =============================================================================

import type {
  McpMarketplaceSummary,
  McpServerScope,
  AvailableMcpServerSummary,
  InstalledMcpServerSummary,
  McpServersCapability,
  McpServersOverviewResult,
} from "@zcode/shared/mcp-server-types";

import type {
  McpSyncCandidate,
  McpSyncImportStatus,
  McpSyncArchiveExportResult,
  McpSyncImportResult,
} from "@zcode/shared/mcp-server-sync";

// Re-export types from shared (consumers may import either from this file or
// from @zcode/shared directly; both are kept in sync).
export type {
  McpMarketplaceSummary,
  McpServerScope,
  AvailableMcpServerSummary,
  InstalledMcpServerSummary,
  McpServersCapability,
  McpServersOverviewResult,
} from "@zcode/shared/mcp-server-types";

export type {
  McpSyncCandidate,
  McpSyncImportStatus,
  McpSyncArchiveExportResult,
  McpSyncImportResult,
} from "@zcode/shared/mcp-server-sync";

// MCP Server Management Service Interface
export interface IMcpServerManagementService {
  /**
   * List all MCP servers for a workspace or user scope
   */
  listServers(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    scope?: McpServerScope;
  }): Promise<InstalledMcpServerSummary[]>;

  /**
   * Get MCP server reference catalog
   */
  getServerReferenceCatalog(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    sessionId?: string;
  }): Promise<McpServerReferenceCatalogResult>;

  /**
   * Resolve suggested MCP server reference
   */
  resolveSuggestedServerReference(params: {
    marketplace?: string;
    slug?: string;
  }): Promise<McpServerReferenceCatalogResult["servers"][0] | null>;

  /**
   * Get MCP servers overview
   */
  getServersOverview(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    scope?: McpServerScope;
  }): Promise<McpServersOverviewResult>;

  /**
   * Add MCP server marketplace source
   */
  addMarketplace(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    source: string;
    scope?: McpServerScope;
  }): Promise<void>;

  /**
   * Remove MCP server marketplace source
   */
  removeMarketplace(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    marketplace: string;
  }): Promise<void>;

  /**
   * Update MCP server marketplace source
   */
  updateMarketplace(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    marketplace?: string;
  }): Promise<void>;

  /**
   * Install MCP server from marketplace
   */
  installServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerInstallResult>;

  /**
   * Cancel ongoing MCP server operation
   */
  cancelServerOperation(params: {
    operationId: string;
  }): Promise<McpServerCancelOperationResult>;

  /**
   * Uninstall MCP server
   */
  uninstallServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerUninstallResult>;

  /**
   * Update MCP server
   */
  updateServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerInstallResult>;

  /**
   * Restore builtin MCP server
   */
  restoreBuiltinServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    scope?: McpServerScope;
  }): Promise<McpServerRestoreBuiltinResult>;

  /**
   * Configure MCP server options
   */
  configureServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
    options: Record<string, string | number | boolean>;
  }): Promise<McpServerConfigureResult>;

  /**
   * Reset MCP server config to defaults
   */
  resetServerConfig(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    scope?: McpServerScope;
  }): Promise<McpServerConfigureResult>;

  /**
   * Validate MCP server configuration
   */
  validateServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerValidateResult>;

  /**
   * Describe MCP server details
   */
  describeServer(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
  }): Promise<McpServerDescribeResult>;

  /**
   * Set MCP server enabled state
   */
  setServerEnabled(params: {
    workspacePath?: string;
    workspaceIdentity?: string;
    serverName: string;
    marketplace: string;
    scope?: McpServerScope;
    enabled: boolean;
  }): Promise<McpServerSetEnabledResult>;
}

// Result Types
export interface McpServerInstallResult {
  success: boolean;
  serverName: string;
  operationId?: string;
  error?: string;
}

export interface McpServerCancelOperationResult {
  success: boolean;
  operationId: string;
}

export interface McpServerUninstallResult {
  success: boolean;
  serverName: string;
  error?: string;
}

export interface McpServerRestoreBuiltinResult {
  success: boolean;
  serverName: string;
  error?: string;
}

export interface McpServerConfigureResult {
  success: boolean;
  serverName: string;
  configuredOptions?: Record<string, string | number | boolean>;
  error?: string;
}

export interface McpServerValidateResult {
  valid: boolean;
  errors?: string[];
  warnings?: string[];
}

export interface McpServerDescribeResult {
  name: string;
  marketplace: string;
  description?: string;
  version?: string;
  author?: string;
  homepage?: string;
  repository?: string;
  categories?: string[];
  tags?: string[];
  installCommand?: string;
  configurationSchema?: Record<string, unknown>;
  capabilities?: string[];
  error?: string;
}

export interface McpServerSetEnabledResult {
  success: boolean;
  serverName: string;
  enabled: boolean;
  error?: string;
}

export interface McpServerReferenceCatalogResult {
  servers: McpServerCatalogEntry[];
  total: number;
  cursor?: string;
}

export interface McpServerCatalogEntry {
  id: string;
  name: string;
  marketplace: string;
  description?: string;
  version?: string;
  author?: string;
  homepage?: string;
  repository?: string;
  stars?: number;
  verified?: boolean;
  categories?: string[];
  tags?: string[];
  installCommand?: string;
  logoUrl?: string;
}

// Service Channel for RPC
export const ServiceChannels = {
  McpServerManagement: "mcp-server-management",
} as const;

// =============================================================================
// ZCode Plugin Sync Types - Ported to EvoFlow MCP Server Management
// Source: ZCode/packages/shared/src/plugin-sync.ts
// Changes: Plugin → MCP Server, plugin → mcp-server
// =============================================================================

export type McpSyncImportStatus = "synced" | "skipped" | "failed";
export type McpSyncComponentType = "skills" | "commands" | "hooks" | "mcp";

export interface McpSyncCandidate {
  id: string;
  name: string;
  pluginId: string;
  directoryName: string;
  description?: string;
  version?: string;
  path: string;
  sizeBytes: number;
  enabled: boolean;
  enabledOverride?: boolean;
  componentTypes: McpSyncComponentType[];
}

export interface McpSyncCandidateListResult {
  candidates: McpSyncCandidate[];
  maxArchiveBytes: number;
}

export interface McpSyncRemoteStatus {
  serverId: string;
  directoryName: string;
  exists: boolean;
  path?: string;
  reason?: "sameServerId" | "targetExists";
}

export interface McpSyncRemoteStatusResult {
  statuses: McpSyncRemoteStatus[];
}

export interface McpSyncArchiveExportResult {
  archive: Uint8Array;
  archiveBytes: number;
  servers: Array<{
    id: string;
    name: string;
    serverId: string;
    directoryName: string;
    enabled?: boolean;
  }>;
}

export interface McpSyncMarketplaceSourceArchiveExportResult {
  archive: Uint8Array;
  archiveBytes: number;
  marketplaceId: string;
  serverNames: string[];
}

export interface McpSyncMarketplaceSourceImportResult {
  marketplaceId: string;
  path: string;
  status: Exclude<McpSyncImportStatus, "failed">;
}

export interface McpSyncImportResultItem {
  name: string;
  serverId: string;
  directoryName: string;
  status: McpSyncImportStatus;
  path?: string;
  error?: string;
}

export interface McpSyncImportResult {
  results: McpSyncImportResultItem[];
}

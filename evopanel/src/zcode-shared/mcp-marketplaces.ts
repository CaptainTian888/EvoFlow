// =============================================================================
// ZCode Plugin Marketplaces - Ported to EvoFlow MCP Server Management
// Source: ZCode/packages/shared/src/plugin-marketplaces.ts
// Changes: Plugin → MCP Server, ZCode → EvoFlow
// =============================================================================

export interface DefaultMcpServerMarketplace {
  id: string;
  source: string;
  name: string;
  description: string;
  serverCount: number;
  lastUpdated?: string;
}

export const EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID = "evoflow-mcp-official";

/** Settings 三类资源发现共用；Bootstrap 单测与官方 definition 的 defaultEnabled 机械对照。 */
export const DEFAULT_ENABLED_OFFICIAL_MCP_SERVER_IDS: ReadonlySet<string> = new Set([
  "filesystem@evoflow-mcp-official",
  "github@evoflow-mcp-official",
  "fetch@evoflow-mcp-official",
  "brave-search@evoflow-mcp-official",
  // 更多官方 MCP...
]);

export const DEFAULT_MCP_MARKETPLACES: DefaultMcpServerMarketplace[] = [
  {
    // EvoFlow 官方唯一市场：本地 seed 分片与 CDN 分片在 Agent storage 内合并。
    // CDN manifest 的 name 必须与该 canonical id 一致。
    id: EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID,
    source: "https://cdn.evoflow.ai/mcp/official/marketplace.json",
    name: EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID,
    description: "Official EvoFlow MCP servers marketplace: built-in and community MCP servers for EvoFlow.",
    serverCount: 0,
  },
];

// 商店「公开」分段只有一个 EvoFlow 官方市场 id，内置与 CDN 不再拆分身份。
export const PUBLIC_STORE_MARKETPLACE_IDS = [EVOFLOW_OFFICIAL_MCP_MARKETPLACE_ID] as const;

export function isPublicStoreMarketplaceId(id: string): boolean {
  return (PUBLIC_STORE_MARKETPLACE_IDS as readonly string[]).includes(id);
}

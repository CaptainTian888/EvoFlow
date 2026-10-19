// =============================================================================
// ZCode Installed Plugin Roots - Ported to Captain Work MCP Server Management
// Source: ZCode/packages/services/src/plugins/installedPluginRoots.ts
// Changes: Plugin → MCP Server
// =============================================================================

import { readFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

interface InstalledMcpServerRoot {
  defaultEnabled: boolean;
  marketplace: string;
  rootPath: string;
}

const INSTALLED_MCP_SERVERS_FILE = "installed_mcp_servers.json";

interface InstalledMcpServerRecord {
  id: string;
  installPath: string;
  marketplace: string;
}

export async function readInstalledMcpServerRoots(
  mcpStorageRoot: string,
): Promise<InstalledMcpServerRoot[]> {
  const records = await readInstalledMcpServerRecords(mcpStorageRoot);
  return records.map((record) => ({
    defaultEnabled: false,
    marketplace: record.marketplace,
    rootPath: record.installPath,
  }));
}

async function readInstalledMcpServerRecords(
  mcpStorageRoot: string,
): Promise<InstalledMcpServerRecord[]> {
  let raw: string;
  try {
    raw = await readFile(join(mcpStorageRoot, INSTALLED_MCP_SERVERS_FILE), "utf-8");
  } catch {
    return [];
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch {
    return [];
  }
  if (!isRecord(parsed) || !Array.isArray(parsed.servers)) {
    return [];
  }

  const records: InstalledMcpServerRecord[] = [];
  for (const item of parsed.servers) {
    if (!isRecord(item)) continue;
    const id = typeof item.id === "string" ? item.id.trim() : "";
    const marketplace = typeof item.marketplace === "string" ? item.marketplace.trim() : "";
    const installPath = typeof item.installPath === "string" ? item.installPath.trim() : "";
    if (!id || !marketplace || !installPath || !isAbsolute(installPath)) {
      continue;
    }
    records.push({ id, installPath, marketplace });
  }
  return records;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

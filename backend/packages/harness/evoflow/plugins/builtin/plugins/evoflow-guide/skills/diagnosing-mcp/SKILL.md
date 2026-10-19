---
name: diagnosing-mcp
description: Use to diagnose and fix EvoFlow MCP (Model Context Protocol) server configuration problems. Applies when an MCP server will not connect, its tools (mcp__server__tool) do not appear, it shows as disabled or failed, connections time out, a command cannot be found, template variables are not expanded, or a server defined in a configuration file has no effect. Provides configuration locations, how to inspect status, common pitfalls, and a step-by-step localization and repair workflow.
---

# Diagnosing MCP Configuration

Goal: reduce any MCP problem to a single concrete file-field or SQLite-row edit.

## 1. Configuration locations and precedence

| Source | Path / Location | Format |
|---|---|---|
| Env override | `$EVOFLOW_MCP_CONFIG` | Any path to a JSON file |
| User default | `{data_base_dir}/mcp.json` (e.g. `~/.evoflow/mcp.json`) | `{"mcpServers": {...}}` or flat `{"name": {...}}` |
| Cursor compat | `~/.cursor/mcp.json` | Same format |
| Unified config | `extensions_config.json` (`$EVOFLOW_EXTENSIONS_CONFIG_PATH` or `{cwd}/`) | `{"mcpServers": {...}, "skills": {...}}` |
| Authoritative | SQLite table `evoflow_mcp_servers` in `{data_root}/app/evoflow.db` | Per-row records |

**Runtime load order**: `load_mcp_config()` reads SQLite first. If SQLite is empty or corrupt, it falls back to `mcp.json` and syncs back to SQLite.

**Override order**: CLI → environment → user → workspace → system. Plugin-provided servers form the base layer.

## 2. Configuration schema

Each server entry supports:
- `type`: `"stdio"` (default) or `"sse"` / `"streamable-http"`
- `command`: required for `stdio` (e.g. `"npx"`, `"python"`)
- `args`: array of string arguments
- `env`: environment variables (supports `$VAR` / `${VAR}` expansion)
- `cwd`: working directory
- `enabled`: boolean (default `true`)
- `timeoutMs`: connection timeout
- `url`: required for `sse` / `streamable-http`
- `headers`: HTTP headers (supports env var expansion)
- `oauth`: OAuth config object
- `description`: human-readable description

## 3. Common symptoms → causes → fixes

### Server not connecting / tools missing

1. **Check SQLite first**: Query `evoflow_mcp_servers` table. If the server is not there, the config file was never seeded.
   - Fix: restart the backend (triggers `seed_config_from_app_yaml()` which reads `mcp.json` → SQLite), or manually insert the row.
2. **Check config file exists**: Verify `~/.evoflow/mcp.json` (or `$EVOFLOW_MCP_CONFIG`) exists and is valid JSON.
   - Fix: create/fix the file, then restart backend.
3. **Check `enabled` field**: If `false` in SQLite or config, the server is skipped.
   - Fix: set `enabled: true`.
4. **Check `command` is on PATH**: For `stdio` servers, the `command` must be executable.
   - Fix: use full path or ensure the binary is installed.

### Tools appear but with wrong names

- EvoFlow names tools as `mcp__{server}__{tool}`. If you see `mcp__github__create_issue`, the server name is `github` and the tool is `create_issue`.
- If the server name contains special characters, they are sanitized. Check the server name in your config.

### Environment variables not expanded

- EvoFlow supports `$VAR` and `${VAR}` syntax in `env`, `headers`, and `args`.
- If a variable is not set in the backend's environment, it expands to empty string.
- Fix: set the variable in the backend's environment, or hardcode the value.

### Connection times out

- Check `timeoutMs` (default varies by transport). Increase if the server is slow to start.
- For `stdio`: check if the command hangs on startup (e.g. waiting for input).
- For `sse`/`streamable-http`: check network connectivity to the `url`.

### Config file changes have no effect

- **SQLite is authoritative**: editing `mcp.json` after initial seed does NOT update running config. You must either:
  - Restart the backend (re-seeds from file if SQLite is empty), or
  - Update SQLite directly, or
  - Use the EvoFlow UI (Settings → MCP) which writes to SQLite.

## 4. Step-by-step diagnosis workflow

1. **Identify the server name** from the error or UI.
2. **Check SQLite**: `SELECT * FROM evoflow_mcp_servers WHERE name = '<server>'` in `{data_root}/app/evoflow.db`.
3. **If not in SQLite**: check `mcp.json` / `extensions_config.json` for the server entry. If missing, add it and restart. If present, the seed may have failed — check backend logs in `{data_root}/logs/`.
4. **If in SQLite but not connecting**: check `enabled`, `command`/`url`, `env` variables. Test the command manually in a terminal.
5. **If connecting but tools missing**: check the server's tool list (some servers expose tools lazily). Check `timeoutMs`. Look for errors in backend logs.
6. **Apply fix**: edit SQLite row or config file + restart, or use the UI.
---
name: diagnosing-plugins
description: Use to diagnose and fix EvoFlow plugin problems. Applies when a plugin is not listed in the marketplace, fails to install, has missing components (skills/commands/hooks/MCP), is not enabled, or its icon does not display. Provides storage layout, install mechanism, enable state, and a step-by-step localization and repair workflow.
---

# Diagnosing Plugins Configuration

Goal: reduce any plugin problem to a concrete file or state edit.

## 1. Storage layout

Plugin storage root: `{EVOFLOW_HOME}/data/plugins/` (or `$EVOFLOW_PLUGIN_STORAGE_ROOT`).

```
{storage_root}/
├── known_marketplaces.json           # marketplace source list
├── installed_plugins.json            # install records + enable/disable state
├── marketplaces/<id>/marketplace.json  # marketplace manifest cache
├── cache/<marketplace>/<name>/<version>/  # installed plugin roots
├── data/<plugin-id>/                 # plugin persistent user data
└── icons/                            # localized plugin icons (served via /api/plugins/icon/<name>)
```

## 2. Key files and their roles

### `installed_plugins.json`

Contains:
- `plugins`: array of `InstalledPluginRecord` (id, name, marketplace, version, installPath, scope, installedAt)
- `enabledPlugins`: `{ "plugin_id": true/false }` — default is **enabled** unless explicitly `false`

### `known_marketplaces.json`

List of marketplace sources (URL, git, local path). The official marketplace (`evoflow-plugins-official`) is seeded automatically.

### `marketplaces/<id>/marketplace.json`

Cached marketplace manifest. Contains the `plugins` array with listings (name, displayName, description, icon, version, source, cachePath).

## 3. Plugin identity

- **Plugin ID**: `{name}@{marketplace_id}` (e.g. `evoflow-guide@evoflow-plugins-official`)
- **Name**: the plugin's `name` field in `.evoflow-plugin/plugin.json` (must match `^[a-z0-9][a-z0-9._-]{0,127}$`)
- **Marketplace ID**: the marketplace's `id` field

## 4. Common symptoms → causes → fixes

### Plugin not listed in marketplace

1. **Check marketplace manifest**: Look in `marketplaces/<id>/marketplace.json` for the plugin entry.
2. **Check `EXCLUDED_OFFICIAL_PLUGINS`**: Some official plugins are intentionally excluded from EvoFlow's marketplace (e.g. `node-repl-host`, `zcode-guide`).
3. **Check marketplace source**: If the plugin comes from a custom marketplace, verify the marketplace is in `known_marketplaces.json` and its manifest is cached.
4. **Refresh marketplace**: Use the UI (Discover tab → refresh) or call `POST /api/plugins/marketplaces/{id}/refresh`.

### Plugin fails to install

1. **Check source type**: `filesystem` (local dir), `zip` (archive), `git` (repo). Each has different resolution logic.
2. **Check `cachePath` exists**: For `filesystem` sources, the `cachePath` must point to a valid directory.
3. **Check manifest validity**: The plugin directory must have `.evoflow-plugin/plugin.json` with at least a `name` field.
4. **Check backend logs**: Installation errors are logged in `{data_root}/logs/`.

### Plugin has missing components

1. **Check directory structure**: The plugin root should have `skills/`, `commands/`, `hooks/` (in manifest), `mcpServers` (in manifest) as needed.
2. **Check manifest `componentTypes`**: The manifest declares which components the plugin provides.
3. **Use `describe` endpoint**: `GET /api/plugins/describe?marketplace=<id>&name=<name>` returns the component enumeration.
4. **Reinstall**: If components were added after initial install, reinstall the plugin to re-enumerate.

### Plugin not enabled

1. **Check `installed_plugins.json`**: Look for the plugin ID in `enabledPlugins`. If `false`, the plugin is disabled.
2. **Enable via UI**: Settings → Plugin Management → toggle the plugin.
3. **Enable via API**: `POST /api/plugins/installed/{plugin_id}/enabled` with `{"enabled": true}`.
4. **Built-in plugins**: Can be disabled but not uninstalled. Re-enabling restores full functionality.

### Plugin icon not displaying

1. **Check icon field in manifest**: The marketplace entry should have an `icon` field (either a CDN URL or `/api/plugins/icon/<name>`).
2. **Check icon file exists**: If `icon` is `/api/plugins/icon/<name>`, verify `{storage_root}/icons/<name>.<ext>` exists.
3. **Check icon was downloaded**: During seeding, `_localize_official_icons()` downloads CDN icons to `{storage_root}/icons/`. If the download failed (network), the icon file is missing.
4. **Frontend fallback**: If no icon resolves, the UI shows a fallback (🧩 emoji or Blocks icon).

## 5. Step-by-step diagnosis workflow

1. **Identify the plugin** by name or ID.
2. **Check install state**: Look in `installed_plugins.json` for the plugin record and enable state.
3. **Check marketplace listing**: Look in the marketplace manifest for the plugin entry.
4. **Check plugin root**: Verify `cache/<marketplace>/<name>/<version>/` exists and has a valid `.evoflow-plugin/plugin.json`.
5. **Check components**: Use `describe` endpoint or inspect the directory structure.
6. **Check enable state**: Verify `enabledPlugins[id]` is not `false`.
7. **Apply fix**: install/enable/reinstall via UI or API, or fix the manifest/directory directly.
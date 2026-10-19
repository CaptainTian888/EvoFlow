---
name: evoflow-configuration-guide
description: Use when configuring EvoFlow's extension resources (MCP servers, slash commands, skills, hooks, and plugins) or instruction files such as AGENTS.md. Explains where each resource is configured, the discovery order, precedence, and merge rules, plus guidance on which location to choose. Use when someone asks how to add an MCP server, command, skill, hook, plugin, or AGENTS.md instructions, where a configuration file lives, why a configuration is not taking effect, or needs routing to a specific diagnostic skill.
---

# EvoFlow Configuration Guide

EvoFlow supports five types of extension resources, plus AGENTS.md instruction files. This skill is the **map**: it tells you where each resource is configured and how conflicts are resolved. For "something is not working, how do I fix it," follow the routing to the `diagnosing-*` skills at the end.

## How things are configured

EvoFlow is a Tauri desktop app with a Python backend (FastAPI gateway). Configuration works at two levels:

- **A person** manages resources through the EvoFlow UI — Settings panels, the `+` menu, and the `/` slash menu in the input box.
- **An agent** repairs configuration by reading and editing the underlying files and SQLite tables directly. The locations and rules below are what an agent uses to find the right file and field.

## Data root: EVOFLOW_HOME

All EvoFlow data lives under a base directory resolved by `config/data_paths.py`:

1. `EVOFLOW_HOME` environment variable (normalized: if it points to a `data` subdir, ascend one level)
2. `~/.evoflow` if it exists
3. `config.yaml` → `paths.base_dir` (written by EvoPanel)
4. Local dev fallback: `cwd/.evoflow`
5. Default: `~/.evoflow`

The data directory is `{base_dir}/data/`, containing:
- `app/evoflow.db` — SQLite (tasks, memory, sessions, **MCP servers**, **skill enable state**)
- `logs/` — gateway logs
- `plugins/` — plugin storage root (marketplaces, installed plugins, icons)

Key environment variables:
- `EVOFLOW_HOME` — base data directory (e.g. `~/.evoflow-dev` for dev)
- `EVOFLOW_SKILLS_PATH` — override skills root
- `EVOFLOW_PLUGIN_STORAGE_ROOT` — override plugin storage
- `EVOFLOW_MCP_CONFIG` — override MCP config file path
- `EVOFLOW_EXTENSIONS_CONFIG_PATH` — override extensions config file path

## The five resources at a glance

| Resource | Form | User scope | Workspace scope | Authority |
|---|---|---|---|---|
| **Skills** | Directory + `SKILL.md` | `~/.evoflow/skills/public/` + `custom/` | `<repo>/.evoflow/skills/` | SQLite `evoflow_skills` (enable state); first same-named wins |
| **Commands** | `.md` file in plugin | Via plugins only | — | Plugin manifest `commands/` dir |
| **MCP** | JSON config | `~/.evoflow/mcp.json` or `extensions_config.json` | — | SQLite `evoflow_mcp_servers` (authoritative) |
| **Hooks** | Plugin manifest `hooks` field | Via plugins only | — | Plugin manifest; code-level middlewares |
| **Plugins** | Directory + `.evoflow-plugin/plugin.json` | `{storage_root}/cache/<marketplace>/<name>/<version>/` | — | `installed_plugins.json` (enable state) |
| **Instructions** | `AGENTS.md` file | `~/.zcode/AGENTS.md` (frontend-managed) | `<repo>/AGENTS.md` | Frontend injection; backend does not parse |

## MCP: configuration and precedence

**Config files** (read at startup, seeded into SQLite):
1. `EVOFLOW_MCP_CONFIG` env var (if set)
2. `{data_base_dir}/mcp.json` (i.e. `~/.evoflow/mcp.json`)
3. `~/.cursor/mcp.json` (Cursor compatibility)

Format supports both `{"mcpServers": {...}}` (IDE nested) and flat `{"serverName": {...}}`.

**Authoritative storage**: SQLite table `evoflow_mcp_servers`. At runtime, `load_mcp_config()` reads SQLite first; if empty/corrupt, falls back to `mcp.json` file and syncs back to SQLite.

**Override order**: CLI → environment → user → workspace → system defaults. Plugin-provided servers form the base layer.

**Auto-connect**: All MCP servers from every scope connect automatically at session start.

**Tool naming**: `mcp__{server_name}__{tool_name}` (e.g. `mcp__github__create_issue`).

## Skills: discovery order

Skills are loaded from multiple roots (`skills/loader.py`):

1. `EVOFLOW_SKILLS_PATH` (if set)
2. `{EVOFLOW_HOME}/skills` → `public/` (system/builtin) + `custom/` (user-installed)
3. `~/.evoflow/skills` (production fallback)
4. Repository checkout `<repo>/skills`
5. `{cwd}/skills`
6. Plugin-contributed: each enabled plugin's `skills/` directory (lowest precedence)
7. Profile-level: `~/.evoflow/profiles/<id>/skills`

Within each root, `public/` is synced from system source (never overwritten by user), `custom/` is user-owned (never overwritten by system). First same-named skill in discovery order wins (higher-precedence shadows the rest).

## Commands: plugin-only

EvoFlow slash commands come from **plugins only** — there is no standalone user command config file. Each plugin's `commands/*.md` files are commands; the filename (without `.md`) is the command name. When a user message starts with `/name`, the command's markdown body is inlined (max 4000 chars).

## Hooks: plugin manifest + code middlewares

Hooks are **not user-configurable files**. They come from:
1. Plugin manifest `hooks` field (declarative, enumerated as metadata)
2. Code-level LangChain middlewares (e.g. `automation_run_guard_middleware`, `goal_auto_continue_middleware`) — not configurable by users

To diagnose hooks, check the plugin manifest's `hooks` key and whether the plugin is enabled.

## Plugins: storage layout

Plugin storage root: `{EVOFLOW_HOME}/data/plugins/` (or `EVOFLOW_PLUGIN_STORAGE_ROOT`).

```
{storage_root}/
├── known_marketplaces.json      # marketplace sources
├── installed_plugins.json       # install records + enable/disable state
├── marketplaces/<id>/marketplace.json  # marketplace manifest cache
├── cache/<marketplace>/<name>/<version>/  # installed plugin roots
├── data/<plugin-id>/            # plugin persistent user data
└── icons/                       # localized plugin icons
```

Enable state: `installed_plugins.json` → `enabledPlugins` key. Default is enabled unless explicitly set to `false`. Built-in plugins can be disabled but not uninstalled.

## AGENTS.md

AGENTS.md is managed by the EvoPanel frontend, not parsed by the backend:
- **User scope**: `~/.zcode/AGENTS.md` — personal defaults for every workspace
- **Workspace scope**: `<repo>/AGENTS.md` — project-specific rules
- **Merge**: user file loads first, workspace file loads later (can narrow/override)
- **Migration**: onboarding can copy `~/.claude/CLAUDE.md` → `~/.zcode/AGENTS.md`
- **Creation**: `/agents` slash command creates/updates workspace `AGENTS.md`

## Choosing where to configure

- Personal, cross-project → user scope (`~/.evoflow/...` or `~/.zcode/AGENTS.md`)
- Team/project-shared, versioned → workspace scope (`<repo>/.evoflow/...` or `<repo>/AGENTS.md`)
- MCP servers → `~/.evoflow/mcp.json` (personal) or `extensions_config.json` (unified); both auto-connect
- Secrets → never commit to version control; use environment variables (`$VAR` / `${VAR}` supported in MCP env/headers/args)

## When something is wrong — route to a diagnostic skill

- MCP server not connecting, tools missing, or timing out → **`diagnosing-mcp`**
- A skill is not discovered, not triggering, shadowed, or disabled → **`diagnosing-skills`**
- A `/command` is missing, overridden, or arguments do not substitute → **`diagnosing-commands`**
- A hook does not trigger or blocks unexpectedly → **`diagnosing-hooks`**
- A plugin is not listed, fails to install, has missing components, or is not enabled → **`diagnosing-plugins`**
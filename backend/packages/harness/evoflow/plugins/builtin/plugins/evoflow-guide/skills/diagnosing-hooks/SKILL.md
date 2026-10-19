---
name: diagnosing-hooks
description: Use to diagnose and fix EvoFlow hook problems. Applies when a hook does not trigger, its matcher does not match, its script is not executable, it blocks unexpectedly, or a plugin's hooks are not enumerated. Explains EvoFlow's hook model (plugin manifest + code middlewares) and provides a step-by-step localization workflow.
---

# Diagnosing Hooks Configuration

Goal: determine whether a hook issue is plugin-level (configurable) or code-level (not user-configurable).

## 1. EvoFlow hook model

EvoFlow hooks come from two layers:

### A. Plugin hooks (declarative, from manifest)

- Defined in the plugin manifest's `hooks` field (`.evoflow-plugin/plugin.json`)
- Enumerated as metadata by `plugins/components.py` — the component type is `hook`
- Hook events are listed in the manifest; the plugin must be enabled for its hooks to be active

### B. Code-level middlewares (not user-configurable)

- LangChain `@hook_config` decorated middlewares in the backend code
- Examples: `automation_run_guard_middleware`, `goal_auto_continue_middleware`
- These control agent execution flow (jump-to model/end) and are **not configurable** by users
- To change their behavior, you must modify the backend code

## 2. Common symptoms → causes → fixes

### Plugin hook not triggering

1. **Check plugin is enabled**: The plugin must be in `installed_plugins.json` with `enabledPlugins[id] != false`.
2. **Check manifest `hooks` field**: Verify the plugin's `.evoflow-plugin/plugin.json` has a `hooks` key with the expected event names.
3. **Check hook event name**: The event must be one of the supported events. Unknown events are silently ignored.
4. **Check hook script**: If the hook references a script, verify it exists in the plugin directory and is executable.

### Hook blocks unexpectedly

- This is likely a **code-level middleware** (e.g. `automation_run_guard_middleware` blocks automated runs in certain conditions).
- Check backend logs in `{data_root}/logs/` for middleware decisions.
- Code-level middlewares are not configurable — you must modify the backend code to change their behavior.

### Hook matcher does not match

- Plugin hooks use declarative matchers defined in the manifest. Check the matcher configuration in `.evoflow-plugin/plugin.json`.
- If the matcher is too narrow, broaden the pattern. If too broad, narrow it.

### Plugin hooks not enumerated

- The plugin must be installed and enabled for `components.py` to enumerate its hooks.
- Check `PluginManagementService.overview()` output — hooks appear under the plugin's components list.

## 3. Step-by-step diagnosis workflow

1. **Determine hook layer**: Is it a plugin hook (manifest `hooks` field) or a code middleware (`@hook_config`)? Only plugin hooks are user-diagnosable.
2. **For plugin hooks**:
   a. Verify the plugin is installed and enabled (`installed_plugins.json`).
   b. Check the manifest `hooks` field for the expected event and matcher.
   c. Check any referenced scripts exist and are executable.
   d. Reinstall or re-enable the plugin if the manifest is malformed.
3. **For code middlewares**:
   a. Check backend logs for middleware decisions.
   b. These are not configurable — modify backend code if behavior must change.
4. **Apply fix**: edit the plugin manifest, enable/disable the plugin, or modify backend code for middlewares.
---
name: diagnosing-commands
description: Use to diagnose and fix EvoFlow slash command problems. Applies when a /command is missing, overridden by another plugin, has frontmatter errors, does not substitute arguments, or its body is not injected. Provides discovery rules, invocation mechanism, and a step-by-step localization and repair workflow.
---

# Diagnosing Commands Configuration

Goal: reduce any command problem to a concrete plugin file edit.

## 1. How commands work in EvoFlow

EvoFlow slash commands come from **plugins only**. There is no standalone user command configuration file.

- Each plugin's `commands/*.md` files are commands
- The filename (without `.md`) is the command name (e.g. `commands/review.md` → `/review`)
- Nested directories join with colon: `commands/review/code.md` → `/review:code`
- A command `.md` file may have YAML frontmatter (`name`, `description`) + body

## 2. Invocation mechanism

When a user message starts with `/name`:
1. The backend matches the token against enabled plugins' command lists (`plugins/runtime.py`)
2. If matched, the command's markdown body is inlined into the message (max 4000 chars, `_INVOKED_COMMAND_BODY_MAX_CHARS`)
3. If not matched, only command metadata (name + description) is injected as context

The regex for command detection: `/(?<![\w/\\-])/([a-zA-Z0-9][a-zA-Z0-9_-]{0,63})` — matches `/name` not preceded by word chars, slashes, or backslashes.

## 3. Common symptoms → causes → fixes

### Command not found

1. **Check plugin is installed and enabled**: The command's parent plugin must be in `installed_plugins.json` with `enabledPlugins[id] != false`.
2. **Check file exists**: Verify `<plugin_root>/commands/<name>.md` exists.
3. **Check file is valid**: The `.md` file must be readable; frontmatter (if present) must be valid YAML.
4. **Check command name**: The filename must match `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`. Names with spaces or special chars are not recognized.

### Command body not injected

1. **Check invocation syntax**: The message must **start with** `/name` (not just contain it mid-message). Only the first token is checked for command invocation.
2. **Check body length**: If the markdown body exceeds 4000 chars, it is truncated. Check if essential content is beyond the cutoff.
3. **Check plugin enable state**: Metadata injection happens for all enabled plugins, but body injection only happens for the invoked command's plugin.

### Command overridden by another plugin

- If two plugins define the same command name, the first enabled plugin in iteration order wins. There is no explicit override mechanism.
- Fix: disable the conflicting plugin, or rename the command in one plugin.

### Frontmatter errors

- If frontmatter exists but is malformed YAML, the command may still load but without `name`/`description` metadata.
- Fix: validate YAML syntax. Use `name` and `description` keys.

## 4. Step-by-step diagnosis workflow

1. **Identify the command name** (e.g. `/review`).
2. **List enabled plugins**: check `installed_plugins.json` → `enabledPlugins`.
3. **Search each enabled plugin** for `commands/<name>.md`.
4. **If found**: check file readability, frontmatter validity, body content.
5. **If not found**: the command's plugin is not installed, not enabled, or the file is missing.
6. **If multiple plugins define it**: the first in iteration order wins. Disable duplicates or rename.
7. **Apply fix**: install/enable the plugin, fix the `.md` file, or rename to avoid conflicts.
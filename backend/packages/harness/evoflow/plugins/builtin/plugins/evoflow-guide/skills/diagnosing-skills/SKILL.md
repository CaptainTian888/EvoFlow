---
name: diagnosing-skills
description: Use to diagnose and fix EvoFlow skill configuration problems. Applies when a skill is not discovered, does not trigger, is shadowed by another skill, is disabled, or its description does not match what was written. Provides discovery order, scope rules, shadowing logic, and a step-by-step localization and repair workflow.
---

# Diagnosing Skills Configuration

Goal: reduce any skill problem to a concrete file or SQLite edit.

## 1. Discovery order and roots

Skills are loaded from multiple roots (`skills/loader.py:305 load_skills()`), in priority order:

1. `EVOFLOW_SKILLS_PATH` (explicit override)
2. `{EVOFLOW_HOME}/skills` → `public/` (system, synced) + `custom/` (user-owned)
3. `~/.evoflow/skills` (production fallback)
4. Repository checkout `<repo>/skills` (via `_skills_root_from_source_tree`)
5. `{cwd}/skills`
6. **Plugin-contributed**: each enabled plugin's `skills/` directory (lowest precedence)
7. **Profile-level**: `~/.evoflow/profiles/<id>/skills`

Within each root:
- `public/` — synced from system source on startup; **never overwrite** (your edits will be lost)
- `custom/` — user-installed; **never overwritten** by system

**First same-named skill wins**: higher-precedence roots shadow lower ones. Plugin skills are always shadowed by user/workspace skills of the same name.

## 2. Skill directory structure

Each skill is a directory containing:
- `SKILL.md` (required) — frontmatter `name` + `description`, then body
- Optional subdirectories: `references/`, `templates/`, `scripts/`, `assets/`
- Optional files: `README.md`, `LICENSE`

The `name` in frontmatter must match `^[a-z0-9][a-z0-9._-]{0,127}$`.

## 3. Common symptoms → causes → fixes

### Skill not discovered

1. **Check the skill root**: Run `evoflow doctor` or check `describe_skills_root_context()` output to see which roots are active.
2. **Check directory placement**: The skill must be in `public/<name>/SKILL.md` or `custom/<name>/SKILL.md` under an active root. A bare `SKILL.md` at the root level is not discovered.
3. **Check `EVOFLOW_SKILLS_PATH`**: If set, only this path is used as the primary root. Other roots become fallbacks.
4. **Check plugin is enabled**: If the skill comes from a plugin, the plugin must be installed AND enabled in `installed_plugins.json`.

### Skill not triggering

1. **Check `description` quality**: The description in frontmatter is what the model uses to decide when to trigger. Vague descriptions = unreliable triggering.
2. **Check skill is enabled**: Query SQLite `evoflow_skills` table. If `enabled = false`, the skill is loaded but never offered to the model.
3. **Check shadowing**: A same-named skill in a higher-precedence root may be loaded instead. Check all roots for the same name.
4. **Check plugin state signature**: If a plugin was recently enabled/disabled, the skill cache may be stale. Restart the backend to rebuild.

### Skill is shadowed

- Discovery order determines shadowing. To override a system skill:
  - Place your version in `custom/` (user-owned, higher precedence than `public/`)
  - Or set `EVOFLOW_SKILLS_PATH` to a custom directory
- Plugin skills are always lowest precedence. To override a plugin skill, create a user-level skill with the same name.

### Skill description doesn't match

- The `description` in frontmatter is the source of truth. If you edited the body but not the frontmatter description, the model still sees the old description.
- `public/` skills are re-synced on startup. Edit `custom/` copy or the system source, not the synced `public/` copy.

## 4. Step-by-step diagnosis workflow

1. **Identify the skill name** and expected root (user / plugin / system).
2. **List active roots**: check `EVOFLOW_SKILLS_PATH`, `EVOFLOW_HOME`, and plugin enable state.
3. **Search all roots** for a directory with that skill name. Note which root takes precedence.
4. **Check `SKILL.md` frontmatter**: valid `name`, non-empty `description`.
5. **Check SQLite enable state**: `SELECT * FROM evoflow_skills WHERE name = '<skill>'`.
6. **If plugin-sourced**: verify the plugin is enabled in `installed_plugins.json`.
7. **Apply fix**: create/edit the skill in the correct root, enable in SQLite, or restart to rebuild cache.
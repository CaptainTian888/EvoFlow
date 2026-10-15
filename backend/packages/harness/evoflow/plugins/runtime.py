"""Plugin runtime integration — exposes installed plugins to the agent runtime.

This module is the bridge between the plugin management domain (storage +
service) and the conversation runtime:

- ``plugin_skill_roots`` feeds plugin ``skills/`` directories into the skills
  discovery pipeline (``skills/loader.py`` extra roots), so enabled plugin
  skills behave exactly like native skills: ``<available_skills>`` directory,
  ``$skill-name`` mentions, ``skill:<name>`` URIs in read/terminal tools.
- ``build_plugin_injection_block`` renders the per-turn ``<plugin_injection>``
  message for plugins picked in the chat composer (``preferred_plugins``
  run context), including the plugin's command markdown bodies — the ZCode
  "select a plugin in the composer, its capabilities apply to this turn" flow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from xml.sax import saxutils

from evoflow.plugins.components import enumerate_plugin_components
from evoflow.plugins.manifest import PluginManifestError, read_plugin_manifest_from_root
from evoflow.plugins.storage import (
    InstalledPluginsState,
    load_installed_plugins_state,
    resolve_installed_plugin_root,
    resolve_storage_root,
)

logger = logging.getLogger(__name__)


def _iter_enabled_plugins(storage_root: Path | None = None):
    root = Path(storage_root) if storage_root else resolve_storage_root()
    try:
        state = load_installed_plugins_state(root)
    except Exception:
        return root, []
    enabled: list[tuple[str, Path]] = []
    for record in state.plugins:
        if not state.is_enabled(record.id):
            continue
        plugin_root = resolve_installed_plugin_root(root, record)
        if plugin_root.is_dir():
            enabled.append((record.id, plugin_root))
    return root, enabled


def enabled_plugin_roots(storage_root: Path | None = None) -> list[tuple[str, Path]]:
    """``(plugin_id, plugin_root)`` for every installed + enabled plugin."""
    return _iter_enabled_plugins(storage_root)[1]


def plugin_skill_roots(storage_root: Path | None = None) -> list[Path]:
    """``<plugin_root>/skills`` directories for the skills discovery pipeline."""
    roots: list[Path] = []
    for _plugin_id, plugin_root in enabled_plugin_roots(storage_root):
        skills_dir = plugin_root / "skills"
        if skills_dir.is_dir():
            roots.append(skills_dir)
    return roots


def plugin_state_signature(storage_root: Path | None = None) -> str:
    """Cheap fingerprint of installed plugin ids + enable states (cache invalidation)."""
    try:
        root = Path(storage_root) if storage_root else resolve_storage_root()
        state = load_installed_plugins_state(root)
    except Exception:
        return ""
    return "|".join(f"{record.id}:{'1' if state.is_enabled(record.id) else '0'}" for record in state.plugins)


def _read_text(path: Path, limit: int = 20_000) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > limit:
        text = text[:limit] + "\n… (truncated)"
    return text


def _frontmatter_body(text: str) -> str:
    """Strip the leading YAML frontmatter from a markdown body, keeping the prompt body."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return text[end + 4 :].strip()
    return text


def _plugin_summary(plugin_root: Path) -> dict[str, Any]:
    manifest = None
    try:
        manifest = read_plugin_manifest_from_root(plugin_root)
    except PluginManifestError:
        manifest = None
    components = enumerate_plugin_components(plugin_root, manifest)
    return {
        "name": manifest.name if manifest else plugin_root.name,
        "description": manifest.description if manifest else None,
        "version": manifest.version if manifest else None,
        "components": components,
    }


def resolve_plugin_id(plugin_ref: str, state: InstalledPluginsState) -> str | None:
    """Accept ``name@marketplace`` ids or bare plugin names."""
    ref = str(plugin_ref or "").strip()
    if not ref:
        return None
    if any(record.id == ref for record in state.plugins):
        return ref
    lowered = ref.lower()
    for record in state.plugins:
        if record.name.lower() == lowered or record.id.lower() == lowered:
            return record.id
    return None


def build_plugin_injection_block(
    plugin_refs: list[str] | None,
    storage_root: Path | None = None,
) -> str:
    """Render the ``<plugin_injection>`` block for composer-selected plugins.

    Includes each plugin's command markdown bodies and skill SKILL.md bodies so
    the model can act on them this turn (ZCode composer plugin semantics).
    """
    refs = [str(ref or "").strip() for ref in (plugin_refs or []) if str(ref or "").strip()]
    if not refs:
        return ""
    root = Path(storage_root) if storage_root else resolve_storage_root()
    try:
        state = load_installed_plugins_state(root)
    except Exception:
        return ""

    resolved: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for ref in refs:
        plugin_id = resolve_plugin_id(ref, state)
        if plugin_id is None or plugin_id in seen or not state.is_enabled(plugin_id):
            continue
        seen.add(plugin_id)
        record = next((item for item in state.plugins if item.id == plugin_id), None)
        if record is None:
            continue
        plugin_root = resolve_installed_plugin_root(root, record)
        if plugin_root.is_dir():
            resolved.append((plugin_id, plugin_root))
    if not resolved:
        return ""

    sections: list[str] = []
    for plugin_id, plugin_root in resolved:
        summary = _plugin_summary(plugin_root)
        lines: list[str] = [f'<plugin id="{saxutils.escape(plugin_id, {chr(34): "&quot;"})}">']
        if summary["description"]:
            lines.append(f"  <description>{saxutils.escape(summary['description'])}</description>")
        commands_body: list[str] = []
        skills_body: list[str] = []
        for group in summary["components"]:
            if group["kind"] == "command":
                commands_dir = plugin_root / "commands"
                for item in group["items"]:
                    command_file = commands_dir / f"{item['name']}.md"
                    body = _frontmatter_body(_read_text(command_file))
                    if body:
                        commands_body.append(
                            f'    <command name="{saxutils.escape(item["name"])}">\n'
                            f"{_indent(body, 6)}\n"
                            f"    </command>"
                        )
            elif group["kind"] == "skill":
                skills_dir = plugin_root / "skills"
                for item in group["items"]:
                    skill_file = skills_dir / item["name"] / "SKILL.md"
                    body = _read_text(skill_file)
                    if body:
                        skills_body.append(
                            f'    <skill name="{saxutils.escape(item["name"])}" location="skill:{saxutils.escape(item["name"])}">\n'
                            f"{_indent(body, 6)}\n"
                            f"    </skill>"
                        )
        if commands_body:
            lines.append("  <plugin_commands>")
            lines.extend(commands_body)
            lines.append("  </plugin_commands>")
        if skills_body:
            lines.append("  <plugin_skills>")
            lines.extend(skills_body)
            lines.append("  </plugin_skills>")
        lines.append("</plugin>")
        sections.append("\n".join(lines))

    if not sections:
        return ""
    intro = (
        "<plugin_injection>\n"
        "The following EvoFlow plugins are activated by the user for this turn. Follow their\n"
        "command instructions when the user invokes a listed command (e.g. \"/name\"), and apply\n"
        "the skill guidance when relevant. Skill files are also reachable via \"skill:<name>\" URIs.\n"
        "用户本轮启用了以下 EvoFlow 插件：用户输入 /<命令名> 时按对应 command 的指令执行；\n"
        "相关任务请应用其 skill 指引；技能文件可用 \"skill:<名称>\" URI 读取。\n"
    )
    return intro + "\n".join(sections) + "\n</plugin_injection>"


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(f"{pad}{line}" if line.strip() else line for line in text.splitlines())

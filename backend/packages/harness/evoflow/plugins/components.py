"""Plugin component enumeration (port of ZCode plugin-components.ts).

Produces the ``components: [{kind, items: [{name, description?}]}]`` groups the
settings UI renders in the detail pane, in the canonical order:
agent / command / skill / hook / mcp.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .manifest import PluginManifest, is_record, read_markdown_frontmatter

COMPONENT_KINDS = ("agent", "command", "skill", "hook", "mcp")


def enumerate_plugin_components(
    root_path: Path,
    manifest: PluginManifest | None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []

    agent_items = _collect_markdown_components(root_path, manifest.agents_field if manifest else None, "agents")
    if agent_items:
        groups.append({"kind": "agent", "items": agent_items})

    command_items = _collect_markdown_components(
        root_path, manifest.commands_field if manifest else None, "commands"
    )
    if command_items:
        groups.append({"kind": "command", "items": command_items})

    skill_items = _collect_skill_components(root_path, manifest.skills_field if manifest else None)
    if skill_items:
        groups.append({"kind": "skill", "items": skill_items})

    hook_items = _collect_hook_components(manifest)
    if hook_items:
        groups.append({"kind": "hook", "items": hook_items})

    mcp_items = _collect_mcp_components(root_path, manifest)
    if mcp_items:
        groups.append({"kind": "mcp", "items": mcp_items})

    return groups


def _collect_markdown_components(
    root_path: Path, manifest_field: Any, default_dir: str
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    if is_record(manifest_field):
        for raw_name, raw_meta in manifest_field.items():
            name = str(raw_name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            description = (
                raw_meta.get("description") if is_record(raw_meta) and isinstance(raw_meta.get("description"), str) else None
            )
            items.append({"name": name, **({"description": description.strip()} if description and description.strip() else {})})

    for directory in _collect_component_dirs(root_path, manifest_field, default_dir):
        try:
            entries = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix == ".md")
        except OSError:
            continue
        for file_path in entries:
            frontmatter = read_markdown_frontmatter(file_path)
            name = frontmatter.get("name") or file_path.stem
            if name in seen:
                continue
            seen.add(name)
            description = frontmatter.get("description")
            items.append({"name": name, **({"description": description} if description else {})})
    return items


def _collect_skill_components(root_path: Path, manifest_field: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_files: set[Path] = set()
    seen_names: set[str] = set()
    for directory in _collect_component_dirs(root_path, manifest_field, "skills"):
        for skill_file in _scan_skill_files(directory):
            if skill_file in seen_files:
                continue
            seen_files.add(skill_file)
            frontmatter = read_markdown_frontmatter(skill_file)
            name = frontmatter.get("name") or skill_file.parent.name
            if name in seen_names:
                continue
            seen_names.add(name)
            description = frontmatter.get("description")
            items.append({"name": name, **({"description": description} if description else {})})
    return items


def _scan_skill_files(root: Path) -> list[Path]:
    """Find SKILL.md files under ``root`` without following symlinks."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file() and entry.name == "SKILL.md":
                    found.append(entry)
                elif entry.is_dir():
                    stack.append(entry)
            except OSError:
                continue
    return found


def _collect_hook_components(manifest: PluginManifest | None) -> list[dict[str, Any]]:
    if manifest is None:
        return []
    hooks_field = manifest.hooks_field
    hooks = None
    if is_record(hooks_field) and is_record(hooks_field.get("hooks")):
        hooks = hooks_field["hooks"]
    elif is_record(hooks_field):
        hooks = hooks_field
    if not hooks:
        return []
    items: list[dict[str, Any]] = []
    for event in hooks.keys():
        name = str(event).strip()
        if name:
            items.append({"name": name})
    return items


def _collect_mcp_components(root_path: Path, manifest: PluginManifest | None) -> list[dict[str, Any]]:
    names: list[str] = []
    mcp_json = root_path / ".mcp.json"
    if mcp_json.is_file():
        try:
            payload = json.loads(mcp_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if is_record(payload):
            servers = payload.get("mcpServers")
            if is_record(servers):
                names.extend(str(key) for key in servers.keys())
    if manifest and is_record(manifest.mcp_servers_field):
        names.extend(str(key) for key in manifest.mcp_servers_field.keys())
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in names:
        cleaned = name.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append({"name": cleaned})
    return items


def _collect_component_dirs(root_path: Path, manifest_field: Any, default_dir: str) -> list[Path]:
    dirs: list[Path] = []
    seen: set[Path] = set()

    def add(raw: str) -> None:
        candidate = (root_path / raw.removeprefix("./")).resolve()
        try:
            candidate.relative_to(root_path.resolve())
        except ValueError:
            return
        if candidate in seen or not candidate.is_dir():
            return
        seen.add(candidate)
        dirs.append(candidate)

    default_path = root_path / default_dir
    if default_path.is_dir():
        add(default_dir)
    if isinstance(manifest_field, str):
        add(manifest_field)
    elif isinstance(manifest_field, list):
        for value in manifest_field:
            if isinstance(value, str):
                add(value)
    return dirs


def component_types_from_groups(groups: list[dict[str, Any]]) -> list[str]:
    """Project component groups into the wire ``componentTypes`` vocabulary."""
    mapping = {
        "agent": "agents",
        "command": "commands",
        "skill": "skills",
        "hook": "hooks",
        "mcp": "mcpServers",
    }
    return [mapping.get(group["kind"], group["kind"]) for group in groups]

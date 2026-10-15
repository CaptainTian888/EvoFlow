"""Manifest parsing for plugin.json / marketplace.json and frontmatter helpers.

Mirrors ZCode adapters/plugins/marketplace.ts parsing rules:
- plugin manifest lookup order: .zcode-plugin / .claude-plugin / .codex-plugin
- marketplace manifest lookup: marketplace.json or .claude-plugin/marketplace.json
- name pattern ``^[a-z0-9][a-z0-9._-]{0,127}$`` for both marketplaces and plugins
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKETPLACE_FILE = "marketplace.json"
CLAUDE_MARKETPLACE_FILE = ".claude-plugin/marketplace.json"
ZCODE_MANIFEST_PATH = ".zcode-plugin/plugin.json"
CLAUDE_MANIFEST_PATH = ".claude-plugin/plugin.json"
CODEX_MANIFEST_PATH = ".codex-plugin/plugin.json"
DEFAULT_VERSION = "0.0.0"
MARKETPLACE_JSON_MAX_BYTES = 10 * 1024 * 1024

MARKETPLACE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
PLUGIN_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")

EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE = "evoflow-plugins-official"

# Marketplace entry fields that are store listing metadata, not plugin manifest
# fields (same allowlist ZCode strips when synthesizing manifests for
# strict:false entries).
LISTING_ONLY_ENTRY_FIELDS = (
    "category",
    "tags",
    "strict",
    "displayName",
    "displayName_i18n",
    "description_i18n",
    "icon",
    "privacyPolicy",
    "termsOfService",
    "heroImage",
    "examplePrompts",
    "examplePrompts_i18n",
    "requiresPaidPlan",
)


class PluginManifestError(Exception):
    """Raised when a plugin or marketplace manifest is missing or invalid."""


@dataclass
class PluginDiagnostic:
    code: str
    message: str
    severity: str = "error"  # "warning" | "error"
    pluginId: str | None = None
    path: str | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.pluginId:
            payload["pluginId"] = self.pluginId
        if self.path:
            payload["path"] = self.path
        return payload


@dataclass
class PluginManifest:
    name: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        value = self.raw.get("version")
        return value if isinstance(value, str) and value.strip() else DEFAULT_VERSION

    @property
    def description(self) -> str | None:
        value = self.raw.get("description")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def author(self) -> str | None:
        value = self.raw.get("author")
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            return value["name"].strip() or None
        return None

    @property
    def author_url(self) -> str | None:
        value = self.raw.get("author")
        if isinstance(value, dict) and isinstance(value.get("url"), str):
            return value["url"].strip() or None
        return None

    @property
    def homepage(self) -> str | None:
        value = self.raw.get("homepage")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def user_config(self) -> dict[str, dict[str, Any]]:
        value = self.raw.get("userConfig")
        return value if isinstance(value, dict) else {}

    @property
    def commands_field(self) -> Any:
        return self.raw.get("commands")

    @property
    def agents_field(self) -> Any:
        return self.raw.get("agents")

    @property
    def skills_field(self) -> Any:
        return self.raw.get("skills")

    @property
    def hooks_field(self) -> Any:
        return self.raw.get("hooks")

    @property
    def mcp_servers_field(self) -> Any:
        return self.raw.get("mcpServers")

    def display_metadata(self) -> dict[str, str]:
        metadata: dict[str, str] = {}
        if self.author:
            metadata["author"] = self.author
        if self.author_url:
            metadata["authorUrl"] = self.author_url
        if self.homepage:
            metadata["homepage"] = self.homepage
        if self.raw.get("version"):
            metadata["version"] = str(self.raw["version"])
        return metadata


def is_record(value: Any) -> bool:
    return isinstance(value, dict)


def validate_plugin_name(name: str) -> str | None:
    if not name or not PLUGIN_NAME_PATTERN.fullmatch(name):
        return f"Invalid plugin name: {name!r} (expected {PLUGIN_NAME_PATTERN.pattern})"
    return None


def find_plugin_manifest_path(root: Path) -> Path | None:
    for relative in (ZCODE_MANIFEST_PATH, CLAUDE_MANIFEST_PATH, CODEX_MANIFEST_PATH):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None


def parse_plugin_manifest_payload(payload: Any, source: str) -> PluginManifest:
    if not is_record(payload):
        raise PluginManifestError(f"Plugin manifest is not a JSON object: {source}")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PluginManifestError(f"Plugin manifest is missing a valid 'name': {source}")
    return PluginManifest(name=name.strip(), raw=payload)


def read_plugin_manifest_from_root(root: Path, fallback_name: str = "") -> PluginManifest | None:
    """Read plugin.json from a plugin root; returns None when no manifest exists."""
    manifest_path = find_plugin_manifest_path(root)
    if manifest_path is None:
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PluginManifestError(f"Failed to read plugin manifest {manifest_path}: {error}") from error
    manifest = parse_plugin_manifest_payload(payload, str(manifest_path))
    return manifest


def resolve_installed_plugin_version(root: Path, entry_version: str | None) -> str:
    """Resolve the display/cache version from the plugin's own manifest."""
    try:
        manifest = read_plugin_manifest_from_root(root)
    except PluginManifestError:
        manifest = None
    if manifest and manifest.raw.get("version") and isinstance(manifest.raw.get("version"), str):
        return str(manifest.raw["version"])
    if entry_version and str(entry_version).strip():
        return str(entry_version)
    return DEFAULT_VERSION


@dataclass
class MarketplaceEntry:
    name: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def source(self) -> Any:
        return self.raw.get("source")

    @property
    def strict(self) -> bool:
        return self.raw.get("strict") is not False

    @property
    def version(self) -> str | None:
        value = self.raw.get("version")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def description(self) -> str | None:
        value = self.raw.get("description")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def dependencies(self) -> list[str]:
        value = self.raw.get("dependencies")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    @property
    def cache_path(self) -> str | None:
        value = self.raw.get("cachePath")
        return value if isinstance(value, str) and value.strip() else None

    def listing(self) -> dict[str, Any] | None:
        """Store listing metadata projected from the raw entry."""
        listing: dict[str, Any] = {}
        if self.description:
            listing["description"] = self.description
        for key in (
            "displayName",
            "displayNameI18n",
            "descriptionI18n",
            "icon",
            "category",
            "author",
            "authorUrl",
            "homepage",
            "privacyPolicy",
            "termsOfService",
            "heroImage",
            "examplePrompts",
            "examplePromptsI18n",
            "requiresPaidPlan",
        ):
            if key in self.raw and self.raw[key] is not None:
                listing[key] = self.raw[key]
        # Directory manifests commonly write snake_case i18n keys; ZCode accepts
        # both spellings when projecting the listing.
        for src_key, dst_key in (
            ("displayName_i18n", "displayNameI18n"),
            ("description_i18n", "descriptionI18n"),
            ("examplePrompts_i18n", "examplePromptsI18n"),
        ):
            if src_key in self.raw and dst_key not in listing:
                listing[dst_key] = self.raw[src_key]
        return listing or None


@dataclass
class MarketplaceManifest:
    name: str
    description: str | None
    plugins: list[MarketplaceEntry]
    allow_cross_marketplace_dependencies_on: set[str]
    plugin_root: str | None
    featured: list[str]
    raw: dict[str, Any]

    def entry(self, plugin_name: str) -> MarketplaceEntry | None:
        for candidate in self.plugins:
            if candidate.name == plugin_name:
                return candidate
        return None


def parse_marketplace_manifest(payload: Any, source: str = "marketplace.json") -> MarketplaceManifest:
    if not is_record(payload):
        raise PluginManifestError(f"Marketplace manifest is not a JSON object: {source}")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PluginManifestError(f"Marketplace manifest is missing a valid 'name': {source}")
    if not MARKETPLACE_NAME_PATTERN.fullmatch(name.strip()):
        raise PluginManifestError(
            f"Marketplace name {name!r} does not match {MARKETPLACE_NAME_PATTERN.pattern}: {source}"
        )
    plugins_raw = payload.get("plugins")
    if not isinstance(plugins_raw, list):
        raise PluginManifestError(f"Marketplace manifest 'plugins' must be an array: {source}")
    entries: list[MarketplaceEntry] = []
    seen: set[str] = set()
    for item in plugins_raw:
        if not is_record(item) or not isinstance(item.get("name"), str):
            continue
        entry_name = str(item["name"]).strip()
        if not entry_name or entry_name in seen:
            continue
        seen.add(entry_name)
        entries.append(MarketplaceEntry(name=entry_name, raw=item))
    cross = payload.get("allowCrossMarketplaceDependenciesOn")
    cross_set = {str(item) for item in cross} if isinstance(cross, list) else set()
    plugin_root = payload.get("pluginRoot")
    featured_raw = payload.get("featured")
    featured = [str(item) for item in featured_raw] if isinstance(featured_raw, list) else []
    description = payload.get("description")
    return MarketplaceManifest(
        name=name.strip(),
        description=description if isinstance(description, str) and description.strip() else None,
        plugins=entries,
        allow_cross_marketplace_dependencies_on=cross_set,
        plugin_root=plugin_root if isinstance(plugin_root, str) else None,
        featured=featured,
        raw=payload,
    )


def find_marketplace_manifest_path(root: Path, subdir: str | None = None) -> Path | None:
    search_root = root / subdir if subdir else root
    for relative in (MARKETPLACE_FILE, CLAUDE_MARKETPLACE_FILE):
        candidate = search_root / relative
        if candidate.is_file():
            return candidate
    return None


def read_marketplace_manifest_from_path(path: Path) -> MarketplaceManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PluginManifestError(f"Failed to read marketplace manifest {path}: {error}") from error
    return parse_marketplace_manifest(payload, str(path))


def create_manifest_from_marketplace_entry(entry: MarketplaceEntry) -> dict[str, Any]:
    """Synthesize plugin.json raw payload for strict:false entries (ZCode parity)."""
    raw = {key: value for key, value in entry.raw.items()}
    for key in LISTING_ONLY_ENTRY_FIELDS:
        raw.pop(key, None)
    raw["name"] = entry.name
    raw["version"] = entry.version or DEFAULT_VERSION
    return raw


# ---------------------------------------------------------------------------
# Markdown frontmatter (minimal `key: value` reader, ZCode parity for the
# name/description fields the settings UI consumes).
# ---------------------------------------------------------------------------

def read_markdown_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key in ("name", "description") and value:
            fields[key] = value
    return fields

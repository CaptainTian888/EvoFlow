"""On-disk plugin storage, byte-compatible with the ZCode CLI layout.

Storage root (default ``{data_root}/plugins``, override with
``EVOFLOW_PLUGIN_STORAGE_ROOT``):

- ``known_marketplaces.json``  — authority list of marketplace sources
- ``installed_plugins.json``   — installed records + per-plugin enable state
- ``marketplaces/<id>/marketplace.json`` — cached marketplace manifests
- ``cache/<marketplace>/<name>/<version>/`` — installed plugin roots
- ``data/<plugin-id>/`` — per-plugin persistent user data directory
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import (
    EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE,
    MarketplaceEntry,
    PluginManifestError,
    is_record,
)

KNOWN_MARKETPLACES_FILE = "known_marketplaces.json"
INSTALLED_PLUGINS_FILE = "installed_plugins.json"

_PLUGIN_ID_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def sanitize_plugin_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", value.strip())
    return cleaned[:127] or "_"


def resolve_storage_root() -> Path:
    override = os.getenv("EVOFLOW_PLUGIN_STORAGE_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    try:
        from evoflow.config.data_paths import resolve_data_root

        return resolve_data_root() / "plugins"
    except Exception:
        return (Path.home() / ".evoflow" / "data" / "plugins").resolve()


def plugin_cache_dir(storage_root: Path, marketplace: str, name: str, version: str) -> Path:
    return storage_root / "cache" / sanitize_plugin_id(marketplace) / sanitize_plugin_id(name) / sanitize_plugin_id(version)


def plugin_data_dir(storage_root: Path, plugin_id: str) -> Path:
    return storage_root / "data" / sanitize_plugin_id(plugin_id)


def marketplace_manifest_path(storage_root: Path, marketplace: str) -> Path:
    return storage_root / "marketplaces" / sanitize_plugin_id(marketplace) / "marketplace.json"


@dataclass
class KnownMarketplaceRecord:
    id: str
    source: dict[str, Any]
    name: str
    addedAt: str
    pluginCount: int
    description: str | None = None
    lastUpdated: str | None = None
    lastRefreshFailure: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "name": self.name,
            "addedAt": self.addedAt,
            "pluginCount": self.pluginCount,
        }
        if self.description:
            payload["description"] = self.description
        if self.lastUpdated:
            payload["lastUpdated"] = self.lastUpdated
        if self.lastRefreshFailure:
            payload["lastRefreshFailure"] = self.lastRefreshFailure
        return payload

    @staticmethod
    def from_json(payload: Any) -> KnownMarketplaceRecord | None:
        if not is_record(payload):
            return None
        record_id = payload.get("id")
        source = payload.get("source")
        name = payload.get("name")
        if not all(isinstance(value, str) and value for value in (record_id, name)):
            return None
        if not is_record(source):
            return None
        return KnownMarketplaceRecord(
            id=str(record_id),
            source=source,
            name=str(name),
            description=payload.get("description") if isinstance(payload.get("description"), str) else None,
            addedAt=str(payload.get("addedAt") or ""),
            lastUpdated=payload.get("lastUpdated") if isinstance(payload.get("lastUpdated"), str) else None,
            lastRefreshFailure=payload.get("lastRefreshFailure") if is_record(payload.get("lastRefreshFailure")) else None,
            pluginCount=int(payload["pluginCount"]) if isinstance(payload.get("pluginCount"), (int, float)) else 0,
        )


@dataclass
class InstalledPluginRecord:
    id: str
    name: str
    marketplace: str
    version: str
    installPath: str
    installedAt: str
    scope: str = "user"
    updatedAt: str | None = None
    dependencies: list[str] = field(default_factory=list)
    source: Any = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "marketplace": self.marketplace,
            "version": self.version,
            "installPath": self.installPath,
            "installedAt": self.installedAt,
            "scope": self.scope,
        }
        if self.updatedAt:
            payload["updatedAt"] = self.updatedAt
        if self.dependencies:
            payload["dependencies"] = list(self.dependencies)
        if self.source is not None:
            payload["source"] = self.source
        return payload

    @staticmethod
    def from_json(payload: Any) -> InstalledPluginRecord | None:
        if not is_record(payload):
            return None
        record_id = payload.get("id")
        name = payload.get("name")
        marketplace = payload.get("marketplace")
        if not all(isinstance(value, str) and value for value in (record_id, name, marketplace)):
            return None
        dependencies = payload.get("dependencies")
        return InstalledPluginRecord(
            id=str(record_id),
            name=str(name),
            marketplace=str(marketplace),
            version=str(payload.get("version") or "0.0.0"),
            installPath=str(payload.get("installPath") or ""),
            installedAt=str(payload.get("installedAt") or ""),
            scope=str(payload.get("scope") or "user"),
            updatedAt=payload.get("updatedAt") if isinstance(payload.get("updatedAt"), str) else None,
            dependencies=[str(item) for item in dependencies] if isinstance(dependencies, list) else [],
            source=payload.get("source"),
        )


@dataclass
class InstalledPluginsState:
    plugins: list[InstalledPluginRecord] = field(default_factory=list)
    enabled_plugins: dict[str, bool] = field(default_factory=dict)
    options: dict[str, dict[str, Any]] = field(default_factory=dict)

    def is_enabled(self, plugin_id: str) -> bool:
        # Installed plugins are enabled unless explicitly disabled (ZCode parity:
        # officialPluginsEnabledByDefault seeds safe plugins as enabled).
        return self.enabled_plugins.get(plugin_id, True) is not False

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "plugins": [record.to_json() for record in self.plugins],
            "enabledPlugins": dict(self.enabled_plugins),
            "options": self.options,
        }


def read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None


def write_json_file_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def load_known_marketplaces(storage_root: Path) -> list[KnownMarketplaceRecord]:
    payload = read_json_file(storage_root / KNOWN_MARKETPLACES_FILE)
    if not is_record(payload):
        return []
    value = payload.get("marketplaces")
    records: list[KnownMarketplaceRecord] = []
    if isinstance(value, list):
        for item in value:
            record = KnownMarketplaceRecord.from_json(item)
            if record:
                records.append(record)
    elif is_record(value):
        for item in value.values():
            record = KnownMarketplaceRecord.from_json(item)
            if record:
                records.append(record)
    return records


def save_known_marketplaces(storage_root: Path, records: list[KnownMarketplaceRecord]) -> None:
    write_json_file_atomic(
        storage_root / KNOWN_MARKETPLACES_FILE,
        {"version": 1, "marketplaces": [record.to_json() for record in records]},
    )


def upsert_known_marketplace(storage_root: Path, record: KnownMarketplaceRecord) -> None:
    known = [item for item in load_known_marketplaces(storage_root) if item.id != record.id]
    known.append(record)
    save_known_marketplaces(storage_root, known)


def load_installed_plugins_state(storage_root: Path) -> InstalledPluginsState:
    payload = read_json_file(storage_root / INSTALLED_PLUGINS_FILE)
    state = InstalledPluginsState()
    if not is_record(payload):
        return state
    plugins_raw = payload.get("plugins")
    if isinstance(plugins_raw, list):
        for item in plugins_raw:
            record = InstalledPluginRecord.from_json(item)
            if record:
                state.plugins.append(record)
    enabled = payload.get("enabledPlugins")
    if is_record(enabled):
        state.enabled_plugins = {str(key): bool(value) for key, value in enabled.items()}
    options = payload.get("options")
    if is_record(options):
        state.options = {
            str(key): dict(value) if is_record(value) else {} for key, value in options.items()
        }
    return state


def save_installed_plugins_state(storage_root: Path, state: InstalledPluginsState) -> None:
    write_json_file_atomic(storage_root / INSTALLED_PLUGINS_FILE, state.to_json())


def load_marketplace_manifest_cached(storage_root: Path, marketplace: str):
    from .manifest import parse_marketplace_manifest

    path = marketplace_manifest_path(storage_root, marketplace)
    payload = read_json_file(path)
    if not is_record(payload):
        return None
    try:
        return parse_marketplace_manifest(payload, str(path))
    except PluginManifestError:
        return None


def save_marketplace_manifest_cache(storage_root: Path, manifest_raw: dict[str, Any]) -> Path:
    name = str(manifest_raw.get("name") or "").strip()
    target = marketplace_manifest_path(storage_root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_file_atomic(target, manifest_raw)
    return target


def ensure_plugin_data_dir(storage_root: Path, plugin_id: str) -> Path:
    path = plugin_data_dir(storage_root, plugin_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_installed_plugin_root(storage_root: Path, record: InstalledPluginRecord) -> Path:
    root = Path(record.installPath) if record.installPath else plugin_cache_dir(
        storage_root, record.marketplace, record.name, record.version
    )
    return root


def copytree_atomic(source: Path, target: Path) -> None:
    """Copy ``source`` to ``target`` via a sibling temp dir + single rename.

    A crash mid-copy never leaves a half-written plugin cache directory behind.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def official_marketplace_record_source() -> dict[str, Any]:
    return {"source": "settings"}

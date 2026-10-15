"""Builtin official marketplace seeding (ZCode ``bundled-plugins`` parity).

The official marketplace mirrors ZCode's own bundled seed semantics:

- When a ZCode CLI installation with the official plugin cache exists on this
  machine (``~/.zcode/cli/plugins/cache/zcode-plugins-official``), its plugins
  (browser-use / computer-use / documents / pdf / presentations / spreadsheets /
  zcode-guide / skill-creator / ...) are exposed with ``filesystem`` sources
  pointing at that cache — the same mechanism ZCode uses for its bundled seed.
  Entries carry the real official store listings (displayName_i18n / category /
  icon) copied from ZCode's official marketplace manifest.
- ``DEFAULT_ENABLED_OFFICIAL_PLUGINS`` mirrors ZCode's ``defaultEnabled``
  content-only plugins: they are installed + enabled automatically on first
  seed so users get them out of the box (computer-use stays default-off, also
  matching ZCode).
- When no ZCode cache exists, the marketplace falls back to two self-contained
  demo plugins shipped inside this package so the store is never empty.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .manifest import EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE
from .storage import load_installed_plugins_state, save_installed_plugins_state

logger = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "builtin"

SEED_MANIFEST_VERSION = 6

# 面向用户展示的 listing 文案统一使用 EvoFlow 品牌（这是 EvoFlow 平台的市场）。
# 仅替换文本字段；插件 name slug、icon URL 等标识保持原样。
_LISTING_TEXT_FIELDS = ("displayName", "description")
_LISTING_I18N_FIELDS = ("displayName_i18n", "description_i18n", "examplePrompts_i18n")
_LISTING_LIST_FIELDS = ("examplePrompts",)


def _rebrand_listing_text(value: str) -> str:
    return value.replace("ZCode", "EvoFlow").replace("zcode", "evoflow")


def _rebrand_entry_text(entry: dict[str, Any]) -> None:
    for field in _LISTING_TEXT_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and "zcode" in value.lower():
            entry[field] = _rebrand_listing_text(value)
    for field in _LISTING_I18N_FIELDS:
        i18n = entry.get(field)
        if isinstance(i18n, dict):
            for locale, text in list(i18n.items()):
                if isinstance(text, str) and "zcode" in text.lower():
                    i18n[locale] = _rebrand_listing_text(text)
        elif isinstance(i18n, list):
            entry[field] = [
                _rebrand_listing_text(text) if isinstance(text, str) and "zcode" in text.lower() else text
                for text in i18n
            ]
    for field in _LISTING_LIST_FIELDS:
        values = entry.get(field)
        if isinstance(values, list):
            entry[field] = [
                _rebrand_listing_text(text) if isinstance(text, str) and "zcode" in text.lower() else text
                for text in values
            ]
    author = entry.get("author")
    if isinstance(author, dict):
        name = author.get("name")
        if isinstance(name, str) and "zcode" in name.lower():
            author["name"] = _rebrand_listing_text(name)

# ZCode official plugin ids exposed in the marketplace (node-repl-host is the
# hidden host runtime and intentionally excluded, matching ZCode).
EXCLUDED_OFFICIAL_PLUGINS = {"node-repl-host"}

# ZCode ``defaultEnabled`` content-only plugins — auto-installed + enabled.
DEFAULT_ENABLED_OFFICIAL_PLUGINS = {
    "browser-use",
    "documents",
    "pdf",
    "presentations",
    "spreadsheets",
    "image-search",
    "plugin-creator",
    "skill-creator",
    "zcode-guide",
}

ZCODE_OFFICIAL_MARKETPLACE_ID = "zcode-plugins-official"


def builtin_plugin_dir(name: str) -> Path:
    return BUILTIN_DIR / "plugins" / name


def _zcode_official_cache_candidates() -> list[Path]:
    override = os.getenv("EVOFLOW_ZCODE_PLUGINS_CACHE_ROOT", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    home = Path.home()
    candidates.append(home / ".zcode" / "cli" / "plugins" / "cache" / ZCODE_OFFICIAL_MARKETPLACE_ID)
    candidates.append(home / ".zcode" / "plugins" / "cache" / ZCODE_OFFICIAL_MARKETPLACE_ID)
    return candidates


def discover_zcode_official_cache() -> Path | None:
    """Latest ZCode official plugin cache root on this machine, if any."""
    for candidate in _zcode_official_cache_candidates():
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    return None


def _load_zcode_official_manifest() -> dict[str, Any] | None:
    for base in (
        Path.home() / ".zcode" / "cli" / "plugins" / "marketplaces" / ZCODE_OFFICIAL_MARKETPLACE_ID,
        Path.home() / ".zcode" / "plugins" / "marketplaces" / ZCODE_OFFICIAL_MARKETPLACE_ID,
    ):
        manifest_path = base / "marketplace.json"
        if manifest_path.is_file():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get("plugins"), list):
                return payload
    return None


def _latest_cache_version_dir(cache_root: Path, plugin_name: str) -> Path | None:
    plugin_dir = cache_root / plugin_name
    if not plugin_dir.is_dir():
        return None
    version_dirs = sorted(
        (d for d in plugin_dir.iterdir() if d.is_dir()),
        key=lambda d: [int(part) if part.isdigit() else 0 for part in d.name.split(".")],
    )
    return version_dirs[-1] if version_dirs else None


def _demo_marketplace_manifest() -> dict[str, Any]:
    plugins: list[dict[str, Any]] = [
        {
            "name": "hello-command",
            "displayName": "Hello Command",
            "displayName_i18n": {"zh-CN": "示例：Hello 命令"},
            "description": "EvoFlow 官方示例：注册一个 /hello 斜杠命令，演示插件的 commands 组件。",
            "version": "1.0.0",
            "category": "examples",
            "tags": ["examples", "commands"],
            "author": {"name": "EvoFlow"},
            "source": "filesystem",
            "cachePath": str(builtin_plugin_dir("hello-command")),
        },
        {
            "name": "evoflow-skill-kit",
            "displayName": "EvoFlow Skill Kit",
            "displayName_i18n": {"zh-CN": "示例：技能包"},
            "description": "EvoFlow 官方示例：内置一个 greeting 技能，演示插件的 skills 组件。",
            "version": "1.0.0",
            "category": "examples",
            "tags": ["examples", "skills"],
            "author": {"name": "EvoFlow"},
            "source": "filesystem",
            "cachePath": str(builtin_plugin_dir("evoflow-skill-kit")),
        },
    ]
    return {
        "name": EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE,
        "description": "EvoFlow 官方插件市场（内置示例，离线可用）。",
        "plugins": plugins,
    }


def build_official_marketplace_manifest() -> dict[str, Any]:
    """Compose the official marketplace manifest.

    Mirrors ZCode's bundled official plugins from the local ZCode installation
    when available; the shipped demo plugins are always appended so the store
    stays installable on any machine.
    """
    plugins: list[dict[str, Any]] = []
    seen: set[str] = set()

    cache_root = discover_zcode_official_cache()
    official_manifest = _load_zcode_official_manifest() if cache_root else None
    if cache_root and official_manifest:
        for raw in official_manifest.get("plugins", []):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name or name in seen or name in EXCLUDED_OFFICIAL_PLUGINS:
                continue
            entry = dict(raw)
            _rebrand_entry_text(entry)
            resolved = _latest_cache_version_dir(cache_root, name)
            if resolved is not None:
                # 有本地缓存的内置插件：与 ZCode bundled seed 相同的 filesystem + cachePath 语义。
                entry["source"] = "filesystem"
                entry["cachePath"] = str(resolved)
                if not entry.get("version"):
                    entry["version"] = resolved.name
            # 其余条目（CDN zip 源等）原样保留 source，商店目录与 ZCode 1:1。
            seen.add(name)
            plugins.append(entry)

    for demo in _demo_marketplace_manifest()["plugins"]:
        if demo["name"] in seen:
            continue
        seen.add(demo["name"])
        plugins.append(demo)

    if not plugins:
        return _demo_marketplace_manifest()

    description = (
        "EvoFlow 官方插件市场（与 ZCode 官方市场 1:1 对齐）。"
        if cache_root and official_manifest
        else "EvoFlow 官方插件市场（内置示例，离线可用）。"
    )
    return {
        "name": EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE,
        "description": description,
        "plugins": plugins,
    }


def seed_official_marketplace(storage_root: Path) -> dict[str, Any]:
    """Ensure the official marketplace manifest cache exists and default-enabled
    plugins are installed; returns the raw manifest."""
    from .storage import load_marketplace_manifest_cached, save_marketplace_manifest_cache

    existing = load_marketplace_manifest_cached(storage_root, EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE)
    if existing is not None and existing.raw.get("__seededVersion") == SEED_MANIFEST_VERSION:
        return existing.raw
    manifest = build_official_marketplace_manifest()
    manifest["__seededVersion"] = SEED_MANIFEST_VERSION
    _localize_official_icons(storage_root, manifest)
    save_marketplace_manifest_cache(storage_root, manifest)
    _install_default_enabled_plugins(storage_root, manifest)
    return manifest


ICON_MAX_BYTES = 2 * 1024 * 1024
ICON_DOWNLOAD_TIMEOUT_SEC = 10


def icons_dir(storage_root: Path) -> Path:
    return storage_root / "icons"


def _localize_official_icons(storage_root: Path, manifest: dict[str, Any]) -> None:
    """Download official CDN icons once into ``<storage>/icons`` and rewrite the
    manifest icon fields to the local ``/api/plugins/icon/<name>`` endpoint, so
    the store shows real ZCode plugin icons without a browser-side CDN round trip."""
    import httpx

    target_dir = icons_dir(storage_root)
    for entry in manifest.get("plugins", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        icon_url = str(entry.get("icon") or "").strip()
        if not name or not icon_url.startswith(("http://", "https://")):
            continue
        suffix = Path(icon_url.split("?", 1)[0]).suffix.lower() or ".png"
        if suffix not in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
            suffix = ".png"
        local_path = target_dir / f"{name}{suffix}"
        if not local_path.is_file():
            try:
                with httpx.Client(follow_redirects=True, timeout=ICON_DOWNLOAD_TIMEOUT_SEC) as client:
                    response = client.get(icon_url)
                if response.status_code != 200 or len(response.content) > ICON_MAX_BYTES:
                    logger.info("Icon download skipped for %s (status=%s size=%s)", name, response.status_code, len(response.content))
                    continue
                target_dir.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(response.content)
            except Exception as error:  # noqa: BLE001 - icon is cosmetic
                logger.info("Icon download failed for %s: %s", name, error)
                continue
        entry["icon"] = f"/api/plugins/icon/{name}"


def _install_default_enabled_plugins(storage_root: Path, manifest: dict[str, Any]) -> None:
    """Auto-install + enable ZCode ``defaultEnabled`` content-only plugins."""
    from datetime import datetime, timezone

    from .manifest import parse_marketplace_manifest, resolve_installed_plugin_version
    from .sources import PluginSourceError, resolve_plugin_source_root
    from .storage import (
        InstalledPluginRecord,
        copytree_atomic,
        ensure_plugin_data_dir,
        marketplace_manifest_path,
        plugin_cache_dir,
        save_installed_plugins_state,
    )

    try:
        parsed = parse_marketplace_manifest(manifest, "builtin-seed")
        state = load_installed_plugins_state(storage_root)
        marketplace_dir = marketplace_manifest_path(storage_root, parsed.name).parent
        changed = False
        for entry in parsed.plugins:
            if entry.name not in DEFAULT_ENABLED_OFFICIAL_PLUGINS:
                continue
            plugin_id = f"{entry.name}@{parsed.name}"
            if any(record.id == plugin_id for record in state.plugins):
                continue
            try:
                resolved = resolve_plugin_source_root(entry, parsed, marketplace_dir, storage_root)
            except (PluginSourceError, Exception) as error:  # noqa: BLE001 - seed must not fail wholesale
                logger.warning("Seed default plugin %s failed: %s", plugin_id, error)
                continue
            try:
                version = resolve_installed_plugin_version(resolved.path, entry.version)
                target = plugin_cache_dir(storage_root, parsed.name, entry.name, version)
                if resolved.path.resolve() != target.resolve():
                    copytree_atomic(resolved.path, target)
                state.plugins.append(
                    InstalledPluginRecord(
                        id=plugin_id,
                        name=entry.name,
                        marketplace=parsed.name,
                        version=version,
                        installPath=str(target),
                        installedAt=datetime.now(timezone.utc).isoformat(),
                        scope="user",
                        source=entry.source,
                    )
                )
                state.enabled_plugins[plugin_id] = True
                ensure_plugin_data_dir(storage_root, plugin_id)
                changed = True
            finally:
                if resolved.cleanup:
                    try:
                        resolved.cleanup()
                    except Exception:  # noqa: BLE001
                        pass
        if changed:
            save_installed_plugins_state(storage_root, state)
            logger.info(
                "Seeded default-enabled official plugins: %s",
                sorted(DEFAULT_ENABLED_OFFICIAL_PLUGINS),
            )
    except Exception:  # noqa: BLE001 - seeding must never break startup
        logger.warning("Default plugin seeding failed", exc_info=True)

"""Plugin management service tests — real files, real temp storage root.

Covers the ZCode-parity storage layout and the install lifecycle end to end
against the bundled official marketplace (filesystem sources, no network).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evoflow.plugins.components import enumerate_plugin_components
from evoflow.plugins.manifest import (
    PluginManifestError,
    parse_marketplace_manifest,
    parse_plugin_manifest_payload,
    read_markdown_frontmatter,
)
from evoflow.plugins.service import PluginManagementService
from evoflow.plugins.storage import (
    load_installed_plugins_state,
    load_known_marketplaces,
    marketplace_manifest_path,
    resolve_installed_plugin_root,
)


@pytest.fixture()
def service(tmp_path: Path) -> PluginManagementService:
    return PluginManagementService(storage_root=tmp_path / "plugins")


def test_builtin_marketplace_seeds_official_record(service: PluginManagementService) -> None:
    overview = service.overview()
    official = [item for item in overview["marketplaces"] if item["isOfficial"]]
    assert len(official) == 1
    record = official[0]
    assert record["id"] == "evoflow-plugins-official"
    assert record["pluginCount"] >= 2
    assert (marketplace_manifest_path(service.storage_root, record["id"])).is_file()
    available_ids = {item["id"] for item in overview["availablePlugins"]}
    assert "hello-command@evoflow-plugins-official" in available_ids
    assert "evoflow-skill-kit@evoflow-plugins-official" in available_ids


def test_marketplace_manifest_parse_and_name_validation() -> None:
    manifest = parse_marketplace_manifest(
        {"name": "team-plugins", "plugins": [{"name": "alpha", "source": "./alpha"}]}
    )
    assert manifest.name == "team-plugins"
    assert manifest.entry("alpha") is not None
    with pytest.raises(PluginManifestError):
        parse_marketplace_manifest({"plugins": []})
    with pytest.raises(PluginManifestError):
        parse_marketplace_manifest({"name": "Bad Name!", "plugins": []})


def test_plugin_manifest_parse_and_frontmatter() -> None:
    manifest = parse_plugin_manifest_payload({"name": "demo", "version": "2.1.0"}, "test")
    assert manifest.version == "2.1.0"
    assert manifest.author is None
    with pytest.raises(PluginManifestError):
        parse_plugin_manifest_payload({"version": "1.0.0"}, "test")
    assert read_markdown_frontmatter(Path("nonexistent.md")) == {}


def test_install_official_plugin_end_to_end(service: PluginManagementService) -> None:
    result = service.install_plugin("evoflow-plugins-official", "hello-command")
    assert result["dependencyClosure"] == ["hello-command@evoflow-plugins-official"]
    assert len(result["installedPlugins"]) == 1
    summary = result["installedPlugins"][0]
    assert summary["enabled"] is True
    assert summary["scope"] == "user"
    assert summary["installPath"] and Path(summary["installPath"]).is_dir()
    assert "commands" in summary["componentTypes"]

    listing = service.list_plugins()
    plugin = next(item for item in listing["plugins"] if item["id"] == "hello-command@evoflow-plugins-official")
    assert plugin["commandRootCount"] == 1
    command_group = next(group for group in plugin["components"] if group["kind"] == "command")
    assert command_group["items"][0]["name"] == "hello"
    assert "招呼" in command_group["items"][0]["description"]

    # installPath follows cache/<marketplace>/<name>/<version>
    root = resolve_installed_plugin_root(service.storage_root, _record_of(service, "hello-command@evoflow-plugins-official"))
    assert (root / ".evoflow-plugin" / "plugin.json").is_file()


def _record_of(service: PluginManagementService, plugin_id: str):
    state = load_installed_plugins_state(service.storage_root)
    return next(record for record in state.plugins if record.id == plugin_id)


def test_install_skill_plugin_and_describe(service: PluginManagementService) -> None:
    service.install_plugin("evoflow-plugins-official", "evoflow-skill-kit")
    described = service.describe_plugin("evoflow-plugins-official", "evoflow-skill-kit")
    kinds = {group["kind"] for group in described["components"]}
    assert "skill" in kinds
    skill_group = next(group for group in described["components"] if group["kind"] == "skill")
    assert skill_group["items"][0]["name"] == "greeting"
    assert described.get("metadata", {}).get("author") == "EvoFlow"


def test_enable_state_persists(service: PluginManagementService) -> None:
    plugin_id = "hello-command@evoflow-plugins-official"
    service.install_plugin("evoflow-plugins-official", "hello-command")
    result = service.set_plugin_enabled(plugin_id, False)
    assert result["enabled"] is False
    state = load_installed_plugins_state(service.storage_root)
    assert state.is_enabled(plugin_id) is False

    listing = service.list_plugins()
    plugin = next(item for item in listing["plugins"] if item["id"] == plugin_id)
    assert plugin["enabled"] is False

    service.set_plugin_enabled(plugin_id, True)
    state = load_installed_plugins_state(service.storage_root)
    assert state.is_enabled(plugin_id) is True


def test_uninstall_removes_record_and_cache(service: PluginManagementService) -> None:
    plugin_id = "hello-command@evoflow-plugins-official"
    service.install_plugin("evoflow-plugins-official", "hello-command")
    record = _record_of(service, plugin_id)
    install_root = resolve_installed_plugin_root(service.storage_root, record)
    assert install_root.is_dir()

    result = service.uninstall_plugin(plugin_id, remove_cache=True)
    assert result["removedPlugin"]["id"] == plugin_id
    assert not install_root.exists()
    overview = service.overview()
    assert not any(item["installed"] and item["id"] == plugin_id for item in overview["availablePlugins"])
    # Removed official plugins become restorable builtins again.
    assert any(item["id"] == plugin_id for item in overview["restorableBuiltins"])


def test_restore_builtin_reinstalls(service: PluginManagementService) -> None:
    plugin_id = "hello-command@evoflow-plugins-official"
    service.install_plugin("evoflow-plugins-official", "hello-command")
    service.uninstall_plugin(plugin_id)
    service.restore_builtin_plugin(plugin_id)
    overview = service.overview()
    assert any(
        item["id"] == plugin_id and item["installed"] for item in overview["availablePlugins"]
    )


def test_install_unknown_plugin_raises(service: PluginManagementService) -> None:
    with pytest.raises(PluginManifestError):
        service.install_plugin("evoflow-plugins-official", "does-not-exist")


def test_local_directory_marketplace_add_refresh_remove(
    service: PluginManagementService, tmp_path: Path
) -> None:
    # Build a real local marketplace with one plugin on disk.
    market_dir = tmp_path / "team-market"
    plugin_dir = market_dir / "tools"
    manifest_dir = plugin_dir / ".zcode-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "tools", "version": "0.3.0", "description": "团队工具插件"}),
        encoding="utf-8",
    )
    (plugin_dir / "commands").mkdir()
    (plugin_dir / "commands" / "deploy.md").write_text(
        "---\ndescription: 执行部署\n---\n执行部署流程。", encoding="utf-8"
    )
    (market_dir / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "team-market",
                "description": "团队内部市场",
                "plugins": [{"name": "tools", "source": "./tools", "version": "0.3.0"}],
            }
        ),
        encoding="utf-8",
    )

    record, _ = service.add_marketplace(str(market_dir))
    assert record.id == "team-market"
    assert record.pluginCount == 1

    result = service.install_plugin("team-market", "tools")
    assert result["installedPlugins"][0]["version"] == "0.3.0"

    _updated, diagnostics = service.refresh_marketplace("team-market")
    assert diagnostics == []
    known_ids = {item.id for item in load_known_marketplaces(service.storage_root)}
    assert "team-market" in known_ids

    service.remove_marketplace("team-market")
    known_ids = {item.id for item in load_known_marketplaces(service.storage_root)}
    assert "team-market" not in known_ids


def test_official_marketplace_id_is_reserved(service: PluginManagementService, tmp_path: Path) -> None:
    market_dir = tmp_path / "imposter"
    market_dir.mkdir()
    (market_dir / "marketplace.json").write_text(
        json.dumps({"name": "evoflow-plugins-official", "plugins": []}),
        encoding="utf-8",
    )
    with pytest.raises(PluginManifestError):
        service.add_marketplace(str(market_dir))


def test_dependency_closure_cycle_is_rejected(service: PluginManagementService, tmp_path: Path) -> None:
    market_dir = tmp_path / "cycle-market"
    (market_dir / ".zcode-plugin").mkdir(parents=True)
    for name in ("a", "b"):
        plugin_dir = market_dir / name
        manifest_dir = plugin_dir / ".zcode-plugin"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (market_dir / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "cycle-market",
                "plugins": [
                    {"name": "a", "source": "./a", "dependencies": ["b"]},
                    {"name": "b", "source": "./b", "dependencies": ["a"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    service.add_marketplace(str(market_dir))
    with pytest.raises(PluginManifestError, match="cycle"):
        service.install_plugin("cycle-market", "a")


def test_component_enumeration_on_bundled_plugin() -> None:
    from evoflow.plugins.builtin import builtin_plugin_dir
    from evoflow.plugins.manifest import read_plugin_manifest_from_root

    root = builtin_plugin_dir("hello-command")
    manifest = read_plugin_manifest_from_root(root)
    assert manifest is not None and manifest.name == "hello-command"
    groups = enumerate_plugin_components(root, manifest)
    kinds = [group["kind"] for group in groups]
    assert kinds == ["command"]
    assert groups[0]["items"] == [{"name": "hello", "description": "打一声来自 EvoFlow 插件体系的招呼"}]


def test_validate_source_reports_local_marketplace(service: PluginManagementService, tmp_path: Path) -> None:
    market_dir = tmp_path / "ok-market"
    market_dir.mkdir()
    (market_dir / "marketplace.json").write_text(
        json.dumps({"name": "ok-market", "plugins": []}), encoding="utf-8"
    )
    result = service.validate_source(str(market_dir))
    assert result["ok"] is True
    assert any(item["severity"] == "warning" for item in result["diagnostics"])
    bad = service.validate_source(str(tmp_path / "missing-dir"))
    assert bad["ok"] is False


def test_configure_and_reset_options(service: PluginManagementService) -> None:
    plugin_id = "hello-command@evoflow-plugins-official"
    service.install_plugin("evoflow-plugins-official", "hello-command")
    service.configure_plugin(plugin_id, {"greeting": "你好"}, clear_option_keys=["legacy"])
    state = load_installed_plugins_state(service.storage_root)
    assert state.options[plugin_id] == {"greeting": "你好"}
    service.reset_plugin_config(plugin_id)
    state = load_installed_plugins_state(service.storage_root)
    assert plugin_id not in state.options


def test_reference_catalog_shapes(service: PluginManagementService) -> None:
    plugin_id = "evoflow-skill-kit@evoflow-plugins-official"
    service.install_plugin("evoflow-plugins-official", "evoflow-skill-kit")
    catalog = service.reference_catalog()
    assert catalog["authority"] == "workspace"
    entry = next(item for item in catalog["plugins"] if item["pluginId"] == plugin_id)
    assert entry["skillQualifiedNames"] == ["evoflow-skill-kit:greeting"]
    assert entry["conflictingPluginIds"] == []

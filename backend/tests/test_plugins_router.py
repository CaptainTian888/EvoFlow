"""Plugin management REST API tests — real FastAPI + real temp storage root."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import plugins as plugins_router


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    storage_root = tmp_path / "home" / "data" / "plugins"
    monkeypatch.setenv("EVOFLOW_PLUGIN_STORAGE_ROOT", str(storage_root))
    monkeypatch.setattr(plugins_router, "require_org_admin", lambda request: None)

    app = FastAPI()
    app.include_router(plugins_router.router)
    return TestClient(app)


def test_overview_seeds_official_marketplace(client: TestClient) -> None:
    resp = client.get("/api/plugins/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["capability"] == {"supported": True}
    official = [item for item in body["marketplaces"] if item.get("isOfficial")]
    assert len(official) == 1
    assert official[0]["id"] == "evoflow-plugins-official"
    assert isinstance(official[0]["source"], dict)
    assert official[0]["pluginCount"] >= 2
    available_ids = {item["id"] for item in body["availablePlugins"]}
    assert "hello-command@evoflow-plugins-official" in available_ids
    # hello-command is not default-enabled, so it must be uninstalled at seed time.
    assert not any(
        item["id"].startswith("hello-command") for item in body["installedPlugins"]
    )


def test_install_enable_uninstall_flow_over_api(client: TestClient) -> None:
    plugin_id = "hello-command@evoflow-plugins-official"

    installed = client.post(
        "/api/plugins/install",
        json={"pluginName": "hello-command", "marketplace": "evoflow-plugins-official"},
    )
    assert installed.status_code == 200, installed.text
    body = installed.json()
    assert body["dependencyClosure"] == [plugin_id]
    assert body["installedPlugins"][0]["enabled"] is True

    overview = client.get("/api/plugins/overview").json()
    match = next(item for item in overview["installedPlugins"] if item["id"] == plugin_id)
    assert match["componentTypes"] == ["commands"]
    assert any(item["id"] == plugin_id and item["installed"] for item in overview["availablePlugins"])

    listing = client.get("/api/plugins/list").json()
    plugin = next(item for item in listing["plugins"] if item["id"] == plugin_id)
    assert plugin["rootPath"] and Path(plugin["rootPath"]).is_dir()
    assert plugin["commandRootCount"] == 1

    disabled = client.post(f"/api/plugins/installed/{plugin_id}/enabled", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    listing = client.get("/api/plugins/list").json()
    plugin = next(item for item in listing["plugins"] if item["id"] == plugin_id)
    assert plugin["enabled"] is False

    removed = client.delete(f"/api/plugins/installed/{plugin_id}?removeCache=true")
    assert removed.status_code == 200, removed.text
    assert removed.json()["removedPlugin"]["id"] == plugin_id

    overview = client.get("/api/plugins/overview").json()
    assert not any(
        item["id"].startswith("hello-command") for item in overview["installedPlugins"]
    )
    assert any(item["id"] == plugin_id for item in overview["restorableBuiltins"])


def test_restore_builtin_endpoint(client: TestClient) -> None:
    plugin_id = "evoflow-skill-kit@evoflow-plugins-official"
    restored = client.post(f"/api/plugins/installed/{plugin_id}/restore")
    assert restored.status_code == 200, restored.text
    catalog = client.get("/api/plugins/reference-catalog").json()
    entry = next(item for item in catalog["plugins"] if item["pluginId"] == plugin_id)
    assert entry["skillQualifiedNames"] == ["evoflow-skill-kit:greeting"]


def test_add_and_remove_local_marketplace_over_api(
    client: TestClient, tmp_path: Path
) -> None:
    market_dir = tmp_path / "api-market"
    plugin_dir = market_dir / "sample"
    (plugin_dir / ".zcode-plugin").mkdir(parents=True)
    (plugin_dir / ".zcode-plugin" / "plugin.json").write_text(
        '{"name": "sample", "version": "1.1.0"}', encoding="utf-8"
    )
    (market_dir / "marketplace.json").write_text(
        '{"name": "api-market", "description": "API 测试市场", "plugins": [{"name": "sample", "source": "./sample"}]}',
        encoding="utf-8",
    )

    added = client.post("/api/plugins/marketplaces", json={"source": str(market_dir)})
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["marketplace"]["id"] == "api-market"
    assert body["marketplace"]["pluginCount"] == 1

    installed = client.post(
        "/api/plugins/install", json={"pluginName": "sample", "marketplace": "api-market"}
    )
    assert installed.status_code == 200
    assert installed.json()["installedPlugins"][0]["version"] == "1.1.0"

    refreshed = client.post("/api/plugins/marketplaces/api-market/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["diagnostics"] == []

    removed = client.delete("/api/plugins/marketplaces/api-market")
    assert removed.status_code == 200
    ids = {item["id"] for item in client.get("/api/plugins/overview").json()["marketplaces"]}
    assert "api-market" not in ids


def test_validate_endpoint(client: TestClient, tmp_path: Path) -> None:
    market_dir = tmp_path / "validate-market"
    market_dir.mkdir()
    (market_dir / "marketplace.json").write_text(
        '{"name": "validate-market", "plugins": []}', encoding="utf-8"
    )
    result = client.post("/api/plugins/marketplaces/validate", json={"source": str(market_dir)})
    assert result.status_code == 200
    body = result.json()
    assert body["ok"] is True
    assert body["compatibility"] == {"runnable": [], "diagnosticOnly": [], "unsupported": []}


def test_describe_endpoint(client: TestClient) -> None:
    client.post(
        "/api/plugins/install",
        json={"pluginName": "hello-command", "marketplace": "evoflow-plugins-official"},
    )
    described = client.get(
        "/api/plugins/describe",
        params={"marketplace": "evoflow-plugins-official", "name": "hello-command"},
    )
    assert described.status_code == 200
    body = described.json()
    kinds = {group["kind"] for group in body["components"]}
    assert "command" in kinds


def test_install_unknown_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/api/plugins/install",
        json={"pluginName": "missing", "marketplace": "evoflow-plugins-official"},
    )
    assert resp.status_code == 404


def test_uninstall_missing_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/plugins/installed/nope@nowhere")
    assert resp.status_code == 404

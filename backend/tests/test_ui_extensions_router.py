"""Gateway ui-extensions 注册 API — AI 全自动接入扩展的通道。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import ui_extensions


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    ext_root = tmp_path / "evoflow-home" / "ui-extensions"
    monkeypatch.setenv("EVOFLOW_UI_EXTENSIONS_DIR", str(ext_root.parent))
    monkeypatch.setattr(ui_extensions, "require_org_admin", lambda request: None)

    app = FastAPI()
    app.include_router(ui_extensions.router)
    return TestClient(app)


def _make_extension_dir(tmp_path: Path, ext_id: str, *, link: bool = False) -> Path:
    src = tmp_path / f"src-{ext_id}"
    src.mkdir()
    manifest = {
        "schema": 1,
        "id": ext_id,
        "name": ext_id,
        "version": "1.0.0",
        "ui": {"kind": "webview", "entry": "http://127.0.0.1:5173"},
        "permissions": ["embed"],
        "service": {"mode": "none", "link": link},
        "bridge": {"origin_allowlist": []},
    }
    (src / "evoflow.extension.json").write_text(json.dumps(manifest), encoding="utf-8")
    (src / "index.html").write_text("<html></html>", encoding="utf-8")
    return src


def test_register_copies_dir_and_lists(client: TestClient, tmp_path: Path) -> None:
    src = _make_extension_dir(tmp_path, "my-ops")
    resp = client.post("/api/ui-extensions", json={"path": str(src)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ext_root = Path(body["install_path"])
    assert ext_root.name == "my-ops"
    assert (ext_root / "evoflow.extension.json").is_file()
    assert (ext_root / "index.html").is_file()

    listed = client.get("/api/ui-extensions").json()
    assert [row["id"] for row in listed["extensions"]] == ["my-ops"]
    assert listed["extensions"][0]["source"] == "api:folder"
    assert Path(listed["registry_path"]).is_file()


def test_register_link_mode_keeps_source(client: TestClient, tmp_path: Path) -> None:
    src = _make_extension_dir(tmp_path, "linked-app", link=True)
    resp = client.post("/api/ui-extensions", json={"path": str(src)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["install_path"] == str(src)
    assert body["source"] == "api:folder-link"
    # 未复制目录
    assert not (Path(client.get("/api/ui-extensions").json()["registry_path"]).parent / "linked-app").exists()


def test_register_rejects_invalid_id(client: TestClient, tmp_path: Path) -> None:
    src = _make_extension_dir(tmp_path, "Bad_ID")
    resp = client.post("/api/ui-extensions", json={"path": str(src)})
    assert resp.status_code == 400
    assert "非法" in resp.json()["detail"]


def test_register_rejects_dir_without_manifest(client: TestClient, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    resp = client.post("/api/ui-extensions", json={"path": str(empty)})
    assert resp.status_code == 400


def test_enabled_toggle_and_uninstall(client: TestClient, tmp_path: Path) -> None:
    src = _make_extension_dir(tmp_path, "toggle-app")
    assert client.post("/api/ui-extensions", json={"path": str(src)}).status_code == 200

    resp = client.put("/api/ui-extensions/toggle-app/enabled", json={"enabled": False})
    assert resp.status_code == 200
    registry_path = Path(client.get("/api/ui-extensions").json()["registry_path"])
    rows = json.loads(registry_path.read_text(encoding="utf-8"))
    assert rows[0]["enabled"] is False

    resp = client.delete("/api/ui-extensions/toggle-app")
    assert resp.status_code == 200
    assert client.get("/api/ui-extensions").json()["extensions"] == []
    # 复制安装的目录应被清理
    assert not (registry_path.parent / "toggle-app").exists()


def test_uninstall_keeps_folder_link_source(client: TestClient, tmp_path: Path) -> None:
    src = _make_extension_dir(tmp_path, "keep-me", link=True)
    client.post("/api/ui-extensions", json={"path": str(src)})
    assert client.delete("/api/ui-extensions/keep-me").status_code == 200
    assert src.is_dir()


def test_direct_manifest_registration(client: TestClient, tmp_path: Path) -> None:
    manifest = {
        "schema": 1,
        "id": "remote-entry",
        "name": "remote",
        "version": "1.0.0",
        "ui": {"kind": "webview", "entry": "https://example.com"},
        "service": {"mode": "none"},
    }
    resp = client.post(
        "/api/ui-extensions",
        json={"manifest": manifest, "install_path": "https://example.com", "source": "ai-agent"},
    )
    assert resp.status_code == 200
    rows = client.get("/api/ui-extensions").json()["extensions"]
    assert rows[0]["source"] == "ai-agent"

    again = client.post(
        "/api/ui-extensions",
        json={"manifest": manifest, "install_path": "https://example.com"},
    )
    assert again.status_code == 200
    rows = client.get("/api/ui-extensions").json()["extensions"]
    assert len(rows) == 1  # 幂等 upsert


def test_registry_with_bom_and_single_object_is_tolerated(client: TestClient, tmp_path: Path) -> None:
    """PowerShell 5.1 Set-Content -Encoding UTF8 产出：带 BOM + 单对象。读取须兼容。"""
    registry_path = Path(client.get("/api/ui-extensions").json()["registry_path"])
    legacy_row = {
        "id": "legacy-ps-row",
        "enabled": True,
        "source": "folder-link",
        "install_path": r"D:\dev\some\project",
        "manifest": {"schema": 1, "id": "legacy-ps-row", "name": "legacy"},
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    # 带 BOM + 单对象（脚本最初的坏形态）
    registry_path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps(legacy_row, ensure_ascii=False).encode("utf-8")
    )
    listed = client.get("/api/ui-extensions").json()
    assert [row["id"] for row in listed["extensions"]] == ["legacy-ps-row"]

    # 带 BOM + 数组
    registry_path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps([legacy_row], ensure_ascii=False).encode("utf-8")
    )
    assert client.get("/api/ui-extensions").json()["extensions"][0]["id"] == "legacy-ps-row"

    # 后续写入落回无 BOM 数组形态
    manifest = {
        "schema": 1,
        "id": "after-fix",
        "name": "after",
        "version": "1.0.0",
        "ui": {"kind": "webview", "entry": "https://example.com"},
        "service": {"mode": "none"},
    }
    assert client.post(
        "/api/ui-extensions",
        json={"manifest": manifest, "install_path": "https://example.com"},
    ).status_code == 200
    raw = registry_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    rows = json.loads(raw.decode("utf-8"))
    assert isinstance(rows, list)
    assert {r["id"] for r in rows} == {"legacy-ps-row", "after-fix"}

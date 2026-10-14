"""UI 扩展注册表 Gateway API — 让 AI / 脚本能像面板一样注册扩展。

背景：扩展注册表原本只有两条通道——EvoPanel 面板 UI（Tauri 命令）和手改
``registry.json``。注册表文件由面板管理（``<evoflow_dir>/ui-extensions/registry.json``），
gateway 侧以同一格式读写即可互通；面板每次展示都会重新读文件，外部写入即时生效。

注册表目录解析优先级（与面板 ``evoflow_dir()`` 对齐）：
1. ``EVOFLOW_UI_EXTENSIONS_DIR``（显式覆盖）
2. ``EVOFLOW_CONFIG_DIR``
3. ``EVOFLOW_HOME`` 指向 ``~/.evoflow[-dev]/profiles/<id>`` 时上溯到 ``~/.evoflow[-dev]``
4. 回退 ``~/.evoflow``
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from evoflow.authz.http_guard import require_org_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui-extensions", tags=["ui-extensions"])

_registry_lock = threading.Lock()


class ExtensionRegisterRequest(BaseModel):
    """注册一个扩展：给 path 走「目录安装」（link 或复制），给 manifest 走「直接登记」。"""

    path: str | None = Field(default=None, description="扩展目录（含 evoflow.extension.json）")
    manifest: dict[str, Any] | None = Field(default=None, description="直接提供 manifest（需同时给 install_path）")
    install_path: str | None = Field(default=None, description="manifest 直登时的运行路径（folder-link）")
    link: bool | None = Field(default=None, description="True=不复制目录只登记路径；缺省跟随 manifest.service.link")
    source: str | None = Field(default=None, description="登记来源标记；缺省按安装方式标记 api:folder / api:folder-link / api")


class ExtensionEnabledRequest(BaseModel):
    enabled: bool = Field(..., description="启用/禁用扩展")


def _home() -> Path:
    return Path.home()


def _config_dir() -> Path:
    """与面板 ``evoflow_dir()`` 相同的解析顺序。"""
    explicit = (os.getenv("EVOFLOW_UI_EXTENSIONS_DIR") or os.getenv("EVOFLOW_CONFIG_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home_env = os.getenv("EVOFLOW_HOME", "").strip()
    if home_env:
        profile = Path(home_env).expanduser().resolve()
        # EVOFLOW_HOME = <evoflow_dir>/profiles/<id> 时上溯两级即共享根。
        if profile.parent.name == "profiles":
            root = profile.parent.parent
            if root.name in (".evoflow", ".evoflow-dev") and root.parent == _home():
                return root
    return _home() / ".evoflow"


def _ui_ext_root() -> Path:
    return _config_dir() / "ui-extensions"


def _registry_path() -> Path:
    return _ui_ext_root() / "registry.json"


def _read_registry() -> list[dict[str, Any]]:
    path = _registry_path()
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"读取扩展注册表失败: {exc}") from exc
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _write_registry(rows: list[dict[str, Any]]) -> None:
    root = _ui_ext_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = _registry_path()
        text = json.dumps(rows, ensure_ascii=False, indent=2)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入扩展注册表失败: {exc}") from exc


def _validate_extension_id(manifest: dict[str, Any]) -> str:
    raw = str(manifest.get("id") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="manifest.id 缺失")
    if len(raw) > 64 or raw[0] not in "abcdefghijklmnopqrstuvwxyz" or not all(
        c.isascii() and (c.islower() or c.isdigit() or c == "-") for c in raw[1:]
    ):
        raise HTTPException(status_code=400, detail=f"manifest.id 非法: {raw!r}（须为小写 kebab-case）")
    return raw


def _upsert_row(manifest: dict[str, Any], install_path: str, source: str) -> dict[str, Any]:
    ext_id = _validate_extension_id(manifest)
    with _registry_lock:
        rows = _read_registry()
        rows = [row for row in rows if row.get("id") != ext_id]
        rows.append(
            {
                "id": ext_id,
                "enabled": True,
                "source": source,
                "install_path": install_path,
                "installed_at": _utc_now_rfc3339(),
                "manifest": manifest,
            }
        )
        _write_registry(rows)
    return {"id": ext_id, "install_path": install_path, "source": source}


def _utc_now_rfc3339() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_manifest_from_dir(src: Path) -> dict[str, Any]:
    manifest_file = src / "evoflow.extension.json"
    if not manifest_file.is_file():
        raise HTTPException(status_code=400, detail=f"目录内未找到 evoflow.extension.json: {src}")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Manifest JSON 无效: {exc}") from exc
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=400, detail="Manifest JSON 须为对象")
    return manifest


@router.get(
    "",
    summary="List UI Extensions",
    description="列出已注册的 UI 扩展（读面板共享的 registry.json）。",
)
async def list_extensions() -> dict[str, Any]:
    return {"extensions": _read_registry(), "registry_path": str(_registry_path())}


@router.post(
    "",
    summary="Register UI Extension",
    description=(
        "注册一个 UI 扩展，等价于面板「选择本地文件夹」。"
        "``path`` 指向含 ``evoflow.extension.json`` 的目录；``service.link=true`` 或 ``link=true`` "
        "时不复制目录只登记路径（monorepo/folder-link），否则复制到 ``<ui-extensions>/<id>/``。"
        "也可直接传 ``manifest`` + ``install_path`` 登记已有目录。"
    ),
)
async def register_extension(http_request: Request, req: ExtensionRegisterRequest) -> dict[str, Any]:
    require_org_admin(http_request)
    if req.manifest is not None:
        manifest = req.manifest
        install_path = str(req.install_path or "").strip()
        if not install_path:
            raise HTTPException(status_code=400, detail="直接登记 manifest 时必须提供 install_path")
        return _upsert_row(manifest, install_path, req.source or "api")

    raw_path = str(req.path or "").strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="必须提供 path（扩展目录）或 manifest")
    src = Path(raw_path).expanduser()
    if not src.is_dir():
        raise HTTPException(status_code=400, detail=f"扩展目录不存在: {src}")
    manifest = _read_manifest_from_dir(src)
    link = req.link if req.link is not None else bool(
        (manifest.get("service") or {}).get("link", False)
    )
    if link:
        return _upsert_row(manifest, str(src), req.source or "api:folder-link")
    dest = _ui_ext_root() / _validate_extension_id(manifest)
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"复制扩展目录失败: {exc}") from exc
    return _upsert_row(manifest, str(dest), req.source or "api:folder")


@router.put(
    "/{ext_id}/enabled",
    summary="Enable / Disable UI Extension",
    description="切换扩展启用状态（与面板开关同一字段）。",
)
async def set_enabled(http_request: Request, ext_id: str, req: ExtensionEnabledRequest) -> dict[str, Any]:
    require_org_admin(http_request)
    with _registry_lock:
        rows = _read_registry()
        row = next((r for r in rows if r.get("id") == ext_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail=f"扩展不存在: {ext_id}")
        row["enabled"] = req.enabled
        _write_registry(rows)
    return {"id": ext_id, "enabled": req.enabled}


@router.delete(
    "/{ext_id}",
    summary="Uninstall UI Extension",
    description="从注册表移除扩展；安装目录在 ui-extensions 根下时一并删除（folder-link 只摘登记不删源目录）。",
)
async def uninstall_extension(http_request: Request, ext_id: str) -> dict[str, Any]:
    require_org_admin(http_request)
    root = _ui_ext_root().resolve()
    with _registry_lock:
        rows = _read_registry()
        row = next((r for r in rows if r.get("id") == ext_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail=f"扩展不存在: {ext_id}")
        rows = [r for r in rows if r.get("id") != ext_id]
        _write_registry(rows)
    install_path = str(row.get("install_path") or "")
    if install_path:
        try:
            dest = Path(install_path).resolve()
            if dest.is_dir() and dest.parent == root:
                shutil.rmtree(dest, ignore_errors=True)
        except OSError:
            logger.debug("ui-extensions: cleanup install_path failed", exc_info=True)
    return {"id": ext_id, "uninstalled": True}

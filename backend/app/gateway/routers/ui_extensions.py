"""UI 扩展注册表 Gateway API — 让 AI / 脚本能像面板一样注册扩展。

注册表文件由面板与 gateway 共享（``<evoflow_dir>/ui-extensions/registry.json``），
读写逻辑抽在 :mod:`evoflow.admin.ui_extensions_registry`（资源包安装器/导出器同源复用）；
面板每次展示都会重读文件，外部写入即时生效。

注册表目录解析优先级（与面板 ``evoflow_dir()`` 对齐）：
1. ``EVOFLOW_UI_EXTENSIONS_DIR``（显式覆盖）
2. ``EVOFLOW_CONFIG_DIR``
3. ``EVOFLOW_HOME`` 指向 ``~/.evoflow[-dev]/profiles/<id>`` 时上溯到 ``~/.evoflow[-dev]``
4. 回退 ``~/.evoflow``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from evoflow.admin.ui_extensions_registry import (
    ExtensionIOError,
    ExtensionNotFoundError,
    ExtensionValidationError,
    read_manifest_from_dir,
    read_registry,
    register_directory,
    registry_path,
)
from evoflow.admin.ui_extensions_registry import (
    remove_row as registry_remove_row,
)
from evoflow.admin.ui_extensions_registry import (
    set_enabled as registry_set_enabled,
)
from evoflow.admin.ui_extensions_registry import (
    upsert_row as registry_upsert_row,
)
from evoflow.authz.http_guard import require_org_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui-extensions", tags=["ui-extensions"])


class ExtensionRegisterRequest(BaseModel):
    """注册一个扩展：给 path 走「目录安装」（link 或复制），给 manifest 走「直接登记」。"""

    path: str | None = Field(default=None, description="扩展目录（含 evoflow.extension.json）")
    manifest: dict[str, Any] | None = Field(default=None, description="直接提供 manifest（需同时给 install_path）")
    install_path: str | None = Field(default=None, description="manifest 直登时的运行路径（folder-link）")
    link: bool | None = Field(default=None, description="True=不复制目录只登记路径；缺省跟随 manifest.service.link")
    source: str | None = Field(default=None, description="登记来源标记；缺省按安装方式标记 api:folder / api:folder-link / api")


class ExtensionEnabledRequest(BaseModel):
    enabled: bool = Field(..., description="启用/禁用扩展")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExtensionValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ExtensionNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get(
    "",
    summary="List UI Extensions",
    description="列出已注册的 UI 扩展（读面板共享的 registry.json）。",
)
async def list_extensions() -> dict[str, Any]:
    try:
        return {"extensions": read_registry(), "registry_path": str(registry_path())}
    except ExtensionIOError as exc:
        raise _http_error(exc) from exc


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
    try:
        if req.manifest is not None:
            install_path = str(req.install_path or "").strip()
            if not install_path:
                raise ExtensionValidationError("直接登记 manifest 时必须提供 install_path")
            return registry_upsert_row(req.manifest, install_path, req.source or "api")

        raw_path = str(req.path or "").strip()
        if not raw_path:
            raise ExtensionValidationError("必须提供 path（扩展目录）或 manifest")
        src = Path(raw_path).expanduser()
        manifest = read_manifest_from_dir(src)  # 提前校验，顺便决定默认 source 标记
        link = req.link if req.link is not None else bool(
            (manifest.get("service") or {}).get("link", False)
        )
        source = req.source or ("api:folder-link" if link else "api:folder")
        return register_directory(src, link=link, source=source)
    except (ExtensionValidationError, ExtensionNotFoundError, ExtensionIOError) as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{ext_id}/enabled",
    summary="Enable / Disable UI Extension",
    description="切换扩展启用状态（与面板开关同一字段）。",
)
async def set_enabled(http_request: Request, ext_id: str, req: ExtensionEnabledRequest) -> dict[str, Any]:
    require_org_admin(http_request)
    try:
        return registry_set_enabled(ext_id, enabled=req.enabled)
    except (ExtensionValidationError, ExtensionNotFoundError, ExtensionIOError) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{ext_id}",
    summary="Uninstall UI Extension",
    description="从注册表移除扩展；安装目录在 ui-extensions 根下时一并删除（folder-link 只摘登记不删源目录）。",
)
async def uninstall_extension(http_request: Request, ext_id: str) -> dict[str, Any]:
    require_org_admin(http_request)
    try:
        registry_remove_row(ext_id)
    except (ExtensionValidationError, ExtensionNotFoundError, ExtensionIOError) as exc:
        raise _http_error(exc) from exc
    return {"id": ext_id, "uninstalled": True}

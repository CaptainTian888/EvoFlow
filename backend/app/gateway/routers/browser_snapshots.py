"""Serve persisted browser screenshot PNGs (UI only; not sent to the model)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from evoflow.authz.http_guard import require_thread_visible

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["browser-snapshots"])


@router.get(
    "/{thread_id}/browser-snapshots/{screenshot_id}",
    summary="Get persisted screenshot (browser / computer-use kernel captures)",
)
async def get_browser_screenshot(request: Request, thread_id: str, screenshot_id: str) -> FileResponse:
    require_thread_visible(request, thread_id)
    from evoflow.tools.builtins.browser_screenshot_store import resolve_screenshot_file

    path = resolve_screenshot_file(thread_id, screenshot_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    # CUA 内核回传的栅格是 JPEG（helper 默认编码），browser 截图是 PNG；
    # 按魔数嗅探而不是写死，避免扩展名/字节不一致。
    media_type = "image/png"
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        magic = b""
    if magic.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    return FileResponse(path, media_type=media_type, filename=path.name)

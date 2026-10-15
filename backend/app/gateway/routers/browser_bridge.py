"""Browser bridge HTTP surface — exposes the EvoFlow browser engine to the
node-repl-host kernel bridge (browser-use plugin's ``control-browser`` skill).

Commands use the ZCode browser command contract verbatim (``method`` + payload
fields, see :mod:`evoflow.tools.builtins.browser_contract`); the engine already
implements it. Single-webview model: ``/api/browser/tabs`` reports the one
shared page as a single-element tab list.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from evoflow.authz.http_guard import require_org_admin

logger = logging.getLogger(__name__)

_BRIDGE_THREAD_ID = "evoflow-node-repl-bridge"
_ENGINE_TIMEOUT_SEC = 60.0


def _org_admin_guard(request: Request) -> None:
    require_org_admin(request)


router = APIRouter(prefix="/api/browser", tags=["browser-bridge"], dependencies=[Depends(_org_admin_guard)])


class BrowserExecuteRequest(BaseModel):
    command: dict[str, Any] = Field(..., description="ZCode browser command (method + payload fields)")
    threadId: str | None = Field(default=None, description="Optional engine session key")


def _get_engine():
    from evoflow.tools.builtins.browser_engine import get_browser_engine

    return get_browser_engine()


@router.post("/execute")
async def execute_command(payload: BrowserExecuteRequest) -> dict[str, Any]:
    """Run one ZCode-style browser command through the browser engine."""
    engine = _get_engine()
    thread_id = payload.threadId or _BRIDGE_THREAD_ID
    result = await asyncio.to_thread(engine.execute, thread_id, payload.command, _ENGINE_TIMEOUT_SEC)
    return result


@router.get("/transport")
async def get_transport() -> dict[str, Any]:
    """当前浏览器传输通道：webview2（内置面板）或 edge（WebView2 失败后的系统回退）。"""
    import os

    from evoflow.tools.builtins.browser_engine import _EVOFLOW_DIR

    transport = "unknown"
    port: int | None = None
    transport_file = os.path.join(_EVOFLOW_DIR, "browser-cdp-transport")
    port_file = os.path.join(_EVOFLOW_DIR, "browser-cdp-http-port")
    try:
        if os.path.isfile(transport_file):
            transport = open(transport_file, encoding="utf-8").read().strip().lower() or "unknown"
    except OSError:
        pass
    try:
        if os.path.isfile(port_file):
            raw = open(port_file, encoding="utf-8").read().strip()
            digits = "".join(ch for ch in raw if ch.isdigit())
            port = int(digits) if digits else None
    except (OSError, ValueError):
        port = None
    return {"transport": transport, "httpPort": port}


@router.get("/tabs")
async def list_tabs() -> dict[str, Any]:
    """Tab list in the browser-client ``BrowserTabSummary`` shape (single webview model)."""
    engine = _get_engine()
    state = await asyncio.to_thread(engine.execute, _BRIDGE_THREAD_ID, {"method": "getState"}, 30.0)
    page_state = state.get("state") or {}
    tab = {
        "tabId": "primary",
        "url": str(page_state.get("url") or "about:blank"),
        "title": str(page_state.get("title") or ""),
        "viewport": page_state.get("viewport") or {"width": 1280, "height": 720},
        "active": True,
    }
    return {"tabs": [tab], "activeTabId": "primary"}

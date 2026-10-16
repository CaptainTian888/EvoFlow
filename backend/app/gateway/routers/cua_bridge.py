"""Computer Use (CUA) bridge HTTP surface.

The node-repl-host kernel's ``computer-use-bridge`` global (overridden by
``plugins/node_repl.py`` bridge setup JS) forwards CUA wire methods here.
Each method executes on the REAL Windows desktop via PowerShell
(``plugins/cua_exec.ps1``): screen capture (System.Drawing), mouse/keyboard
injection (user32 SendInput). ZCode's own build ships this closed; this is
EvoFlow's platform implementation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from evoflow.authz.http_guard import require_org_admin

logger = logging.getLogger(__name__)


def _org_admin_guard(request: Request) -> None:
    require_org_admin(request)


def _bridge_token_guard(request: Request) -> None:
    """CUA 命令面共享令牌校验（同 browser bridge，内核桥为唯一预期调用方）。"""
    from evoflow.plugins.bridge_auth import verify_bridge_token

    if not verify_bridge_token(request):
        raise HTTPException(status_code=403, detail="browser bridge token required")


router = APIRouter(prefix="/api/cua", tags=["cua-bridge"], dependencies=[Depends(_org_admin_guard)])


class CuaExecuteRequest(BaseModel):
    method: str = Field(..., description="CUA wire method (get_app_state, left_click, type, key, scroll, list_apps...)")
    input: dict[str, Any] = Field(default_factory=dict, description="Method payload")


_PS_EXEC_PATH = Path(__file__).resolve().parents[3] / "packages" / "harness" / "evoflow" / "plugins" / "cua_exec.ps1"


def _resolve_ps1() -> Path:
    if _PS_EXEC_PATH.is_file():
        return _PS_EXEC_PATH
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "plugins" / "cua_exec.ps1"
        if candidate.is_file():
            return candidate
    raise RuntimeError("cua_exec.ps1 not found next to the gateway or in the harness package")


def _run_ps_action(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    ps1 = _resolve_ps1()
    payload_json = json.dumps(payload, ensure_ascii=False)
    encoded = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", str(ps1),
        "-Action", action,
        "-EncodedPayload", encoded,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"cua_exec.ps1 failed: {(proc.stderr or proc.stdout)[-400:]}")
    return json.loads(proc.stdout)


@router.post(
    "/execute",
    dependencies=[Depends(_bridge_token_guard)],
)
async def execute(payload: CuaExecuteRequest) -> dict[str, Any]:
    """Execute one CUA wire method on the real Windows desktop."""
    from evoflow.tools.builtins.browser_debug_log import browser_debug_log

    method = payload.method
    started = asyncio.get_event_loop().time()
    browser_debug_log("py", f"[cua] execute start method={method} input_keys={sorted(dict(payload.input or {}).keys())}")
    action_map = {
        # wire method → ps1 Action
        "get_app_state": "get_app_state",
        "list_apps": "list_apps",
        "request_access": "request_access",
        "stop_computer_control": "stop_computer_control",
        "screenshot": "screenshot",
    }
    ps_action = action_map.get(method)
    ps_input = dict(payload.input)
    if ps_action is None:
        # 动作方法（left_click/type/key/scroll/...）直接透传给 ps1 分发
        ps_action = method
    try:
        raw = await asyncio.to_thread(_run_ps_action, ps_action, ps_input)
    except Exception as exc:  # noqa: BLE001 — 统一转 CallToolResult 错误
        logger.warning("CUA execute %s failed: %s", method, exc)
        browser_debug_log(
            "py",
            f"[cua] execute FAILED method={method} after {asyncio.get_event_loop().time() - started:.1f}s: {exc}",
        )
        return {
            "content": [{"type": "text", "text": json.dumps({"kind": "cua_error", "message": str(exc)[:300]})}],
            "isError": True,
        }
    browser_debug_log(
        "py",
        f"[cua] execute done method={method} ok={bool(raw.get('ok'))} after {asyncio.get_event_loop().time() - started:.1f}s",
    )
    return _to_call_tool_result(method, raw)


def _to_call_tool_result(method: str, raw: dict[str, Any]) -> dict[str, Any]:
    if not raw.get("ok"):
        err = raw.get("error") or {}
        return {
            "content": [{"type": "text", "text": json.dumps(err, ensure_ascii=False)}],
            "isError": True,
        }
    result = raw.get("result") or {}
    # get_app_state / screenshot：图片块 + 状态文本（客户端 getAXState 解析 text + image 块）
    if method in ("get_app_state", "screenshot") and result.get("base64"):
        state_text = json.dumps(
            {"kind": "visual_only", "note": "v1 视觉模式：无辅助功能树，按截图坐标操作", "screen": {"width": result.get("width"), "height": result.get("height")}},
            ensure_ascii=False,
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": state_text}]
        return {"content": content + [{"type": "image", "data": result["base64"], "mimeType": result.get("mime", "image/png")}]}
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

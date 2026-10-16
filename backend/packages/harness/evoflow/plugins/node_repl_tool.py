"""``mcp__node_repl__js`` — Browser Use / Computer Use kernel tool.

Registered only when one of the dependent official plugins (browser-use /
computer-use) is installed + enabled and the node-repl-host runtime exists.
The official plugin skills hard-require this exact tool name.

Result plumbing (v2 对齐 ZCode 观察面):

- 模型内容 = 内核 text block 原文（无障碍树 / 命令输出），截图不进模型上下文
  （与 browser 截图同一纪律：UI 可见，模型不可见）。
- 截图 image block → ``browser_screenshot_store`` 落盘 → 结果文本尾部附一行
  ``{evoflow-cua-display:...}`` JSON 标记，v4 投影层据此构建 ``kind:"cua"``
  展示块（media.artifactUri + targetApp）。
- ``_meta``（``zcode.cua/app-associations-v1``，helper 的应用身份证据）同样
  进 display 标记，UI 才能渲染目标应用徽标。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_NODE_REPL_JS_DESCRIPTION = (
    "Browser Use and Computer Use only. Run JavaScript in a fresh Node-backed kernel "
    "with top-level await only as instructed by the corresponding official skill to "
    "control a browser or computer. Owns the Browser Use and Computer Use bridges. "
    "Always provide the required `title` as a short user-facing description in the "
    "user's language that describes the intended action without implementation terms "
    "such as js, JavaScript, or node_repl."
)

_DISPLAY_MARKER_PREFIX = "{evoflow-cua-display:"


class NodeReplJsInput(BaseModel):
    # 显示契约（对齐 ZCode node-repl-host 的 JS_TOOL_DESCRIPTION）：面板折叠条
    # 的主标题直接取该字段渲染。前端对含实现术语的标题有过滤兜底，但约束
    # 首先在这里生效——模型每次调用都必须自述一句用户视角的操作意图。
    title: str = Field(
        description=(
            "Required short user-facing description in the user's language that "
            "describes the intended action without implementation terms such as "
            "js, JavaScript, or node_repl."
        ),
        min_length=1,
    )
    code: str = Field(description="JavaScript code to execute in the Node REPL session")
    timeout_ms: int | None = Field(
        default=None,
        ge=1,
        le=120_000,
        description="Per-call timeout in milliseconds (max 120000).",
    )


def _get_thread_id(runtime: ToolRuntime[Any, Any]) -> str:
    ctx = getattr(runtime, "context", None)
    tid = None
    if isinstance(ctx, dict):
        tid = ctx.get("thread_id")
    elif ctx is not None:
        tid = getattr(ctx, "thread_id", None)
    if not tid:
        config = getattr(runtime, "config", None)
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        if isinstance(configurable, dict):
            tid = configurable.get("thread_id")
    return str(tid or "evoflow")


def _save_kernel_image(thread_id: str, image_b64: str, mime_type: str) -> dict[str, Any] | None:
    # helper 回传的栅格是 JPEG（默认编码）或 PNG；统一落进 browser 截图存储
    # （文件名 .png，服务端点按魔数嗅探 content-type，无需区分扩展名）。
    mime = (mime_type or "").lower()
    if mime and mime not in ("image/png", "image/jpeg"):
        return None
    try:
        image_bytes = base64.b64decode(image_b64, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not image_bytes:
        return None
    from evoflow.tools.builtins.browser_screenshot_store import save_screenshot_png

    meta = save_screenshot_png(thread_id, image_bytes)
    return {"url": str(meta["image_url"]), "kb": int(meta["size_kb"])}


def _display_marker(payload: dict[str, Any]) -> str:
    return _DISPLAY_MARKER_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "}"


def _run(code: str, timeout_ms: int | None = None, title: str = "", runtime: ToolRuntime[Any, Any] | None = None) -> str:
    # `title` 仅用于面板显示，不转发给 node-repl-host。
    from evoflow.plugins.node_repl import call_node_repl_js_structured

    kwargs: dict[str, Any] = {"code": code}
    if timeout_ms:
        kwargs["timeout_ms"] = timeout_ms
    thread_id = _get_thread_id(runtime) if runtime is not None else "evoflow"
    # 真实会话 id → 宿主 broker 按会话隔离状态并仲裁桌面控制器租约
    # （两个对话同时开电脑控制时，后到的拿到 CONTROLLER_BUSY 而不是互相打断）。
    kwargs["session_id"] = f"evoflow-thread:{thread_id}"
    result = call_node_repl_js_structured(**kwargs)
    text = str(result.get("text") or "")
    if result.get("is_error"):
        # 报错也走同一通道：把已有文本 + 标记交给上层（Projector 仍可渲染失败态），
        # 模型侧则看到带错误说明的正文，而不是裸 RuntimeError。
        text = text or str(result.get("error") or "node_repl js failed")
        text = f"{text}\n\n[node_repl] call failed."[:4000]

    display: dict[str, Any] = {"status": "failed" if result.get("is_error") else "success"}
    image_entries: list[dict[str, Any]] = []
    for image in (result.get("images") or [])[:2]:
        saved = _save_kernel_image(thread_id, str(image.get("data") or ""), str(image.get("mime_type") or ""))
        if saved:
            image_entries.append(saved)
    if image_entries:
        display["images"] = image_entries
        text = (
            f"{text}\n\n[Screenshot captured: {image_entries[0]['url']} "
            f"({image_entries[0]['kb']}KB) — shown in the chat UI.]"
        ).strip()

    meta = result.get("meta") or {}
    # 宿主 broker 把目标应用身份记在 result._meta["zcode/nodeReplCuaApp"]
    # （appKey: "windows-exe:…" / "windows-aumid:…" / "darwin:…"）；
    # ZCode 的 app-associations-v1（带内联图标）作为兼容通道一并读取。
    app_identity: dict[str, Any] | None = None
    candidate = meta.get("zcode/nodeReplCuaApp")
    if isinstance(candidate, dict) and candidate.get("appKey"):
        app_identity = {
            "app_key": str(candidate["appKey"]),
            **(
                {"display_name": str(candidate["displayName"])}
                if isinstance(candidate.get("displayName"), str) and candidate["displayName"].strip()
                else {}
            ),
        }
    if app_identity is None:
        associations = meta.get("zcode.cua/app-associations-v1")
        if isinstance(associations, dict):
            primary = associations.get("primary")
            if isinstance(primary, dict) and primary.get("appKey"):
                app_identity = {
                    "app_key": str(primary["appKey"]),
                    **(
                        {"display_name": str(primary["displayName"])}
                        if isinstance(primary.get("displayName"), str) and primary["displayName"].strip()
                        else {}
                    ),
                }
    if app_identity:
        display["target_app"] = app_identity

    return f"{text}\n\n{_display_marker(display)}"


def build_node_repl_js_tool() -> Any | None:
    """Build the ``mcp__node_repl__js`` tool, or None when unavailable."""
    if not _is_available():
        return None

    @tool("mcp__node_repl__js", description=_NODE_REPL_JS_DESCRIPTION, args_schema=NodeReplJsInput)
    def node_repl_js(title: str, code: str, timeout_ms: int | None = None, runtime: ToolRuntime[Any, Any] = None) -> str:
        return _run(code, timeout_ms, title, runtime)

    logger.info("node_repl kernel tool registered (mcp__node_repl__js)")
    return node_repl_js


def _is_available() -> bool:
    from evoflow.plugins.node_repl import is_node_repl_available

    return is_node_repl_available()

"""``mcp__node_repl__js`` — Browser Use / Computer Use kernel tool.

Registered only when one of the dependent official plugins (browser-use /
computer-use) is installed + enabled and the node-repl-host runtime exists.
The official plugin skills hard-require this exact tool name.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool
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


class _NodeReplJsInput(BaseModel):
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


def _run(code: str, timeout_ms: int | None = None, title: str = "") -> str:
    # `title` 仅用于面板显示，不转发给 node-repl-host。
    from evoflow.plugins.node_repl import call_node_repl_js

    kwargs: dict[str, Any] = {"code": code}
    if timeout_ms:
        kwargs["timeout_ms"] = timeout_ms
    return call_node_repl_js(**kwargs)


def build_node_repl_js_tool() -> StructuredTool | None:
    """Build the ``mcp__node_repl__js`` tool, or None when unavailable."""
    from evoflow.plugins.node_repl import is_node_repl_available

    if not is_node_repl_available():
        return None
    tool = StructuredTool.from_function(
        func=_run,
        coroutine=None,
        name="mcp__node_repl__js",
        description=_NODE_REPL_JS_DESCRIPTION,
        args_schema=_NodeReplJsInput,
    )
    logger.info("node_repl kernel tool registered (mcp__node_repl__js)")
    return tool

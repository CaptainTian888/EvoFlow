"""Shared staging of tool-captured screenshots into ``viewed_images``.

Both the node_repl (computer control) and browser tools stage screenshots as
``auto`` entries in ``viewed_images`` — path-only graph state, no base64 in
checkpoints. ``ViewImageMiddleware`` reads the files back and injects the
budget-compressed pixels before the next model call (aligned with ZCode's
prepareForModel path, base64 ≤ 200KB).

Keys of the contract:
- ``auto`` entries inject without requiring a ``view_image`` tool call;
- staging is skipped when the main model lacks vision or the user chose the
  text route (image routing keeps old "UI-only" behavior);
- the Command round-trip needs a real tool call id — direct invocations
  degrade to the plain text payload.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)


def stage_image_entry(*, runtime: Any | None, path: str, mime_type: str, label: str) -> dict[str, Any] | None:
    """Build an auto ``ViewedImageData`` entry, or None when native pixels won't be used."""
    if not path:
        return None
    from evoflow.agents.image_routing import decide_view_image_route

    try:
        if decide_view_image_route(runtime=runtime) != "native":
            return None
    except Exception:
        logger.debug("view_image route decision failed; skip staging", exc_info=True)
        return None
    return {"path": path, "mime_type": mime_type, "auto": True, "label": label}


def command_with_staged_images(
    payload: str, tool_call_id: str, staged_entries: dict[str, dict[str, Any]]
) -> str | Command:
    """Return a Command that also stages ``viewed_images``, or the plain payload."""
    if not staged_entries:
        return payload
    if not tool_call_id:
        # ToolMessage 需要真实 call id 才能随 Command 回填图状态；
        # 直连调用（无注入 id）时退化为纯文本结果。
        return payload
    message = ToolMessage(content=payload, tool_call_id=tool_call_id)
    return Command(update={"messages": [message], "viewed_images": staged_entries})

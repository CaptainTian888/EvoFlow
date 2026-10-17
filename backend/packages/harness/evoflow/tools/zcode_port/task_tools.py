"""TaskOutput and TaskStop — ZCode background-task control.

Sources:
- ZCode packages/contracts/src/tools/task-output.ts
- ZCode packages/contracts/src/tools/task-stop.ts
- ZCode packages/core/src/tool/handlers/task-output.ts
- ZCode packages/core/src/tool/handlers/task-stop.ts
"""

from __future__ import annotations

import json
import time

from langchain.tools import tool

from evoflow.tools.zcode_port.background import get_task, stop_task, wait_task
from evoflow.tools.zcode_port.prelude import TASK_OUTPUT_DESCRIPTION, TASK_STOP_DESCRIPTION


def _read_output(path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(output unreadable: {exc})"


@tool("taskoutput", description=TASK_OUTPUT_DESCRIPTION, parse_docstring=False)
def task_output_tool(task_id: str, block: bool | str = True, timeout: int | str = 30_000) -> str:
    """Retrieves output from a running or completed background task.

    task_id: The task ID to get output from.
    block: Whether to wait for completion. Default true.
    timeout: Max wait time in ms. Default 30000, max 600000.
    """
    if not str(task_id or "").strip():
        return "errorCode: 1\nmessage: Task ID is required"
    should_block = block if isinstance(block, bool) else str(block).strip().lower() not in {"false", "0", "no"}
    try:
        timeout_ms = max(0, min(int(timeout), 600_000))
    except (TypeError, ValueError):
        timeout_ms = 30_000
    task = get_task(task_id)
    if task is None:
        return f"errorCode: 2\nmessage: No task found with ID: {task_id}"
    if should_block and task.status == "running":
        task = wait_task(task_id, timeout_ms) or task
    if task.status == "running":
        retrieval = "not_ready" if not should_block else "timeout"
    else:
        retrieval = "success"
    output = _read_output(task.output_path) if task.output_path.exists() else ""
    return (
        f"<retrieval_status>{retrieval}</retrieval_status>\n"
        f"<task_id>{task.task_id}</task_id>\n"
        f"<task_type>bash</task_type>\n"
        f"<status>{task.status}</status>\n"
        f"<description>{task.description}</description>\n"
        f"<exitCode>{task.exit_code}</exitCode>\n"
        f"<outputFile>{task.output_path}</outputFile>\n"
        f"<output>\n{output[-32000:]}\n</output>"
    )


@tool("taskstop", description=TASK_STOP_DESCRIPTION, parse_docstring=False)
def task_stop_tool(task_id: str | None = None, shell_id: str | None = None) -> str:
    """Stops a running background task by its ID.

    task_id: The ID of the background task to stop.
    shell_id: Deprecated: use task_id instead.
    """
    resolved = (task_id or shell_id or "").strip()
    if not resolved:
        return "Error: Missing required parameter: task_id"
    existing = get_task(resolved)
    if existing is None:
        return f"Error: No task found with ID: {resolved}"
    if existing.status != "running":
        return f"Error: Task {resolved} is not running (status: {existing.status})"
    stopped = stop_task(resolved)
    if stopped is None:
        return f"Error: No task found with ID: {resolved}"
    # Give the pump thread a moment to notice the kill.
    time.sleep(0.05)
    return json.dumps(
        {
            "message": f"Successfully stopped task: {stopped.task_id} ({stopped.command})",
            "task_id": stopped.task_id,
            "task_type": "bash",
            "command": stopped.command,
        },
        ensure_ascii=False,
    )

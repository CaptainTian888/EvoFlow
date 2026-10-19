"""ZCode-shaped <task-notification> for local_bash (formatTaskNotification local_bash branch)."""

from __future__ import annotations

import html
import re

_TASK_NOTIFICATION_MAX_CHARS = 120_000


def _escape(value: str) -> str:
    return html.escape(str(value or ""), quote=False)


def format_local_bash_task_notification(
    *,
    task_id: str,
    status: str,
    summary: str,
    output_file: str | None = None,
    tool_use_id: str | None = None,
) -> str:
    lines = ["<task-notification>", f"<task-id>{_escape(task_id)}</task-id>"]
    if tool_use_id:
        lines.append(f"<tool-use-id>{_escape(tool_use_id)}</tool-use-id>")
    if output_file:
        lines.append(f"<output-file>{_escape(output_file)}</output-file>")
    lines.append(f"<status>{_escape(status)}</status>")
    lines.append(f"<summary>{_escape(summary)}</summary>")
    lines.append("</task-notification>")
    text = "\n".join(lines)
    if len(text) <= _TASK_NOTIFICATION_MAX_CHARS:
        return text
    return text[: _TASK_NOTIFICATION_MAX_CHARS - 20] + "\n…[truncated]"


def normalize_bash_notification_status(status: str) -> str:
    s = str(status or "").strip().lower()
    if s in {"completed", "failed", "running", "timed_out", "spawn_error"}:
        return s
    if s in {"stopped", "cancelled", "canceled", "killed"}:
        return "killed"
    if s == "resultpending":
        return "completed"
    return s or "completed"


def build_bash_task_summary(
    *,
    command: str,
    description: str,
    exit_code: int | None,
    status: str,
) -> str:
    subject = (description or command or "background bash").strip()
    subject = re.sub(r"\s+", " ", subject)[:160]
    st = normalize_bash_notification_status(status)
    if st == "killed":
        return f"Background bash stopped: {subject}"
    if st == "failed":
        code = f" (exit {exit_code})" if exit_code is not None else ""
        return f"Background bash failed{code}: {subject}"
    if st == "completed":
        return f"Background bash completed: {subject}"
    return f"Background bash {st}: {subject}"

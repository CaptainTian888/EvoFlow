"""REST surface for ZCode-aligned background Bash tasks (status panel + detail + stop)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/background-bash", tags=["background-bash"])


@router.get("")
def list_background_bash(
    running_only: bool = Query(default=True),
    thread_id: str | None = Query(default=None),
):
    from evoflow.tools.zcode_port.background import list_tasks, task_to_summary

    tasks = list_tasks(running_only=running_only, thread_id=thread_id)
    return {"works": [task_to_summary(t) for t in tasks]}


@router.get("/{work_id}/output")
def background_bash_output(work_id: str):
    from evoflow.tools.zcode_port.background import get_task, read_output_snapshot

    task = get_task(work_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"No task found with ID: {work_id}")
    return read_output_snapshot(task)


@router.post("/{work_id}/stop")
def background_bash_stop(work_id: str):
    from evoflow.tools.zcode_port.background import get_task, stop_task, task_to_summary

    existing = get_task(work_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No task found with ID: {work_id}")
    if existing.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Task {work_id} is not running (status: {existing.status})",
        )
    stopped = stop_task(work_id)
    if stopped is None:
        raise HTTPException(status_code=404, detail=f"No task found with ID: {work_id}")
    return {
        "ok": True,
        "message": f"Successfully stopped task: {stopped.task_id} ({stopped.command})",
        "work": task_to_summary(stopped),
    }

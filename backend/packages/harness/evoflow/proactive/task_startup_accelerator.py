"""Task startup acceleration: wake agent immediately when task is assigned.

When a new task is created and assigned to an agent, instead of waiting for
the next patrol tick (up to 60 seconds), immediately notify the agent to pick
it up. This reduces task startup delay from ~2 min to < 5 seconds.

Design:
  1. Task creation flow detects assigned_to field
  2. If assigned_to is a role, emit "task_assigned" event
  3. Event triggers immediate patrol dispatch (debounce = 0)
  4. Agent wakes up and finds the new task
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def maybe_wake_agent_for_new_task(
    task: dict[str, Any],
    runner: Any | None = None,
) -> None:
    """Schedule immediate agent wake-up if a task is just assigned.
    
    Args:
        task: The task dict (from collab_tasks table)
        runner: ProactiveRunner instance (if available, used for async firing)
    
    Returns:
        None (fires async in background)
    """
    assigned_to = str(task.get("assigned_to") or "").strip()
    if not assigned_to:
        return  # No assignment, nothing to do
    
    task_name = str(task.get("name") or "").strip()
    if not task_name:
        return  # Anonymous task, skip
    
    logger.info(
        "task_startup_accelerator: waking %s for new task %s",
        assigned_to,
        task.get("task_id") or "?",
    )
    
    if runner:
        try:
            import asyncio
            
            # Fire async event: emit with debounce=0 (immediate)
            async def _wake():
                from evoflow.proactive.triggers import get_event_bus
                
                bus = get_event_bus()
                if bus:
                    await bus.emit(
                        event_type="task_assigned",
                        agent_code=assigned_to,
                        goal=f"新任务已分配: {task_name}",
                        description=f"Task ID: {task.get('task_id')}",
                    )
            
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_wake())
            except RuntimeError:
                # No running loop, skip
                pass
        except Exception as e:
            logger.debug("task_startup_accelerator: wake emit failed: %s", e, exc_info=True)

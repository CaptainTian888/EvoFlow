"""Patch langgraph_runtime_inmem ``listen_for_cancellation`` 240s 超时退出缺陷。

vendor 版监听 task 在 240s 无消息后 ``TimeoutError: break`` 退出 —— 长任务（>240s）
此后用户点停止，cancel control message 无人消费 → 协作式取消失效 → agent 跑到自然
结束，而 run 状态早已被标 interrupted（UI/DB 均显示「已停」），形成「已停还在跑」。

监听 task 由 ``Runs.enter`` 的 SimpleTaskGroup 管理（Runs.enter 退出时被 cancel），
本就无需 timeout；本 patch 改为永久 ``await queue.get()``，并补 [STOP-TRACE] 日志
作为「worker 真正收到取消」的证明（全链路唯一能证明真停的观测点）。

Runs.enter 在函数体内按模块全局名引用 ``listen_for_cancellation``，替换模块属性
即可生效，无需触碰 .venv（venv 重建后 patch 仍随代码生效）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_PATCHED = False


def apply_langgraph_cancellation_patch() -> bool:
    """Patch ``langgraph_runtime_inmem.ops.listen_for_cancellation`` once per process."""
    global _PATCHED
    if _PATCHED:
        return True
    try:
        import langgraph_runtime_inmem.ops as inmem_ops
        from langgraph_runtime_inmem.inmem_stream import get_stream_manager
    except ImportError:
        logger.debug("langgraph_runtime_inmem unavailable; skip cancellation patch")
        return False

    async def _patched_listen_for_cancellation(
        queue: asyncio.Queue,
        run_id: UUID,
        thread_id: UUID | None,
        done: Any,
    ) -> None:
        from langgraph_api.errors import UserInterrupt, UserRollback  # noqa: PLC0415

        stream_manager = get_stream_manager()

        if control_key := stream_manager.get_control_key(run_id, thread_id):
            payload = control_key.data
            if payload == b"rollback":
                done.set(UserRollback())
            elif payload == b"interrupt":
                done.set(UserInterrupt())

        while not done.is_set():
            # vendor 版：asyncio.wait_for(queue.get(), timeout=240) 超时 break ——
            # 长任务 240s 后监听退出，cancel control message 无人消费，协作式取消失效。
            # 本 task 由 Runs.enter 的 SimpleTaskGroup 管理（退出时被 cancel），无需 timeout。
            message = await queue.get()
            payload = message.data
            if payload == b"rollback":
                logger.warning("[STOP-TRACE] 7.worker-rollback-received run=%s", run_id)
                done.set(UserRollback())
            elif payload == b"interrupt":
                logger.warning("[STOP-TRACE] 7.worker-interrupt-received run=%s", run_id)
                done.set(UserInterrupt())
            elif payload == b"done":
                done.set()
                break

    inmem_ops.listen_for_cancellation = _patched_listen_for_cancellation
    _PATCHED = True
    logger.info("Applied langgraph_runtime_inmem listen_for_cancellation patch（无 240s 超时退出 + STOP-TRACE 日志）")
    return True


__all__ = ["apply_langgraph_cancellation_patch"]
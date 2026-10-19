"""[STOP-TRACE] 停止链路修复的单元测试。

覆盖：
- langgraph_cancellation_patch：替换成功 + 幂等 + patched listen 行为（interrupt/done/无消息持续等待）
- langgraph_cancel.sweep：空转返回 ([], []) + 正常 cancel 路径
- commands._post_stop_reconcile：leaked → 二次 cancel → ok / 多轮 leaked → exhausted
- commands._schedule_post_stop_reconcile：创建后台任务 + done callback 清理

Run: cd backend && python -m pytest tests/test_stop_trace_and_reconcile.py -v
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import httpx
import pytest

from evoflow.session_execution import commands
from evoflow.session_execution import langgraph_cancel

_RUN_ID = uuid.uuid4()


# ── patch ──────────────────────────────────────────────────────────────


class _FakeDone:
    """模拟 langgraph_api.asyncio.ValueEvent 的最小契约。"""

    def __init__(self) -> None:
        self._set = False
        self.value = None

    def is_set(self) -> bool:
        return self._set

    def set(self, value=None) -> None:  # noqa: A003
        self._set = True
        self.value = value


def test_apply_cancellation_patch_replaces_module_attr():
    """patch 应替换 langgraph_runtime_inmem.ops.listen_for_cancellation。"""
    try:
        import langgraph_runtime_inmem.ops as inmem_ops
    except ImportError:
        pytest.skip("langgraph_runtime_inmem 不在测试环境")
    original = inmem_ops.listen_for_cancellation
    try:
        from evoflow.langgraph_cancellation_patch import (
            apply_langgraph_cancellation_patch,
            _PATCHED as _before,  # noqa: F401
        )
    except ImportError:
        pytest.skip("patch 模块不可导入")

    ok = apply_langgraph_cancellation_patch()
    assert ok is True
    assert inmem_ops.listen_for_cancellation is not original
    # 幂等
    again = apply_langgraph_cancellation_patch()
    assert again is True


@pytest.mark.asyncio
async def test_patched_listen_interrupt_sets_done():
    """收到 b"interrupt" control message → done.set(UserInterrupt())。"""
    try:
        from langgraph_runtime_inmem.inmem_stream import Message
        from langgraph_api.errors import UserInterrupt
    except ImportError:
        pytest.skip("langgraph vendor 包不在测试环境")

    from evoflow.langgraph_cancellation_patch import apply_langgraph_cancellation_patch

    apply_langgraph_cancellation_patch()
    import langgraph_runtime_inmem.ops as inmem_ops

    queue: asyncio.Queue = asyncio.Queue()
    done = _FakeDone()
    await queue.put(Message(topic=b"run:x:control", data=b"interrupt"))

    await inmem_ops.listen_for_cancellation(queue, _RUN_ID, None, done)
    assert done.is_set()
    assert isinstance(done.value, UserInterrupt)


@pytest.mark.asyncio
async def test_patched_listen_done_message_exits():
    """收到 b"done" → done.set() 且循环退出（task 完成）。"""
    try:
        from langgraph_runtime_inmem.inmem_stream import Message
    except ImportError:
        pytest.skip("langgraph vendor 包不在测试环境")

    from evoflow.langgraph_cancellation_patch import apply_langgraph_cancellation_patch

    apply_langgraph_cancellation_patch()
    import langgraph_runtime_inmem.ops as inmem_ops

    queue: asyncio.Queue = asyncio.Queue()
    done = _FakeDone()
    await queue.put(Message(topic=b"run:x:control", data=b"done"))

    await inmem_ops.listen_for_cancellation(queue, _RUN_ID, None, done)
    assert done.is_set()


@pytest.mark.asyncio
async def test_patched_listen_waits_indefinitely_without_message():
    """无消息时监听持续等待（证明无短 timeout 主动退出）。

    vendor 版 240s 后会 break；patched 版应持续等待直到被 cancel。
    用 0.3s 探测窗口 + cancel 终止证明它没有自己退出。
    """
    try:
        import langgraph_runtime_inmem.ops as inmem_ops  # noqa: F401
    except ImportError:
        pytest.skip("langgraph vendor 包不在测试环境")

    from evoflow.langgraph_cancellation_patch import apply_langgraph_cancellation_patch

    apply_langgraph_cancellation_patch()
    import langgraph_runtime_inmem.ops as inmem_ops

    queue: asyncio.Queue = asyncio.Queue()
    done = _FakeDone()
    task = asyncio.create_task(inmem_ops.listen_for_cancellation(queue, _RUN_ID, None, done))
    await asyncio.sleep(0.3)
    assert not task.done(), "监听 task 不应在无消息时主动退出"
    assert not done.is_set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── sweep ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sweep_empty_returns_empty(monkeypatch):
    """thread 无 active runs → 返回 ([], [])（空转路径，现已留痕）。"""

    async def _empty_fetch(client, tid):
        return []

    monkeypatch.setattr(langgraph_cancel, "_fetch_thread_runs", _empty_fetch)
    async with httpx.AsyncClient() as client:
        cancelled, orphans = await langgraph_cancel.sweep_langgraph_runs_until_idle(client, "t1")
    assert cancelled == []
    assert orphans == []


@pytest.mark.asyncio
async def test_sweep_cancels_active_run(monkeypatch):
    """active run → cancel POST 成功 → run 离开 active → 返回 cancelled。"""
    state = {"cancelled": False}

    async def _fetch(client, tid):
        if state["cancelled"]:
            return []
        return [{"run_id": "r1", "status": "running"}]

    async def _post_cancel(client, tid, rid):
        state["cancelled"] = True
        return "cancelled"

    monkeypatch.setattr(langgraph_cancel, "_fetch_thread_runs", _fetch)
    monkeypatch.setattr(langgraph_cancel, "_post_cancel_run", _post_cancel)
    async with httpx.AsyncClient() as client:
        cancelled, orphans = await langgraph_cancel.sweep_langgraph_runs_until_idle(client, "t1")
    assert cancelled == ["r1"]
    assert orphans == []


# ── reconcile ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_ok_when_run_leaves_active(monkeypatch):
    """第一轮 leaked → 二次 cancel → 第二轮空 → reconcile-ok 退出。"""
    state = {"round": 0}

    async def _list_active(client, tid, **kw):
        state["round"] += 1
        return ["r1"] if state["round"] == 1 else []

    async def _cancel_ids(client, tid, ids, **kw):
        return list(ids)

    monkeypatch.setattr(langgraph_cancel, "list_active_langgraph_run_ids", _list_active)
    monkeypatch.setattr(langgraph_cancel, "cancel_langgraph_run_ids", _cancel_ids)
    monkeypatch.setattr(commands, "_POST_STOP_RECONCILE_DELAY_S", 0.05)
    monkeypatch.setattr(commands, "_POST_STOP_RECONCILE_ROUNDS", 3)

    await commands._post_stop_reconcile("s1", "t1", ["r1"])
    assert state["round"] == 2


@pytest.mark.asyncio
async def test_reconcile_exhausted_when_still_active(monkeypatch, caplog):
    """多轮复查仍 active → reconcile-exhausted 告警（无异常）。"""

    async def _list_active(client, tid, **kw):
        return ["r1"]

    async def _cancel_ids(client, tid, ids, **kw):
        return list(ids)

    monkeypatch.setattr(langgraph_cancel, "list_active_langgraph_run_ids", _list_active)
    monkeypatch.setattr(langgraph_cancel, "cancel_langgraph_run_ids", _cancel_ids)
    monkeypatch.setattr(commands, "_POST_STOP_RECONCILE_DELAY_S", 0.05)
    monkeypatch.setattr(commands, "_POST_STOP_RECONCILE_ROUNDS", 2)

    with caplog.at_level(logging.WARNING):
        await commands._post_stop_reconcile("s1", "t1", ["r1"])
    assert any("reconcile-exhausted" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_schedule_reconcile_creates_and_tracks_task(monkeypatch):
    """_schedule_post_stop_reconcile 创建后台任务，完成后从 _pending 集合移除。"""
    called = {"n": 0}

    async def _noop_reconcile(s, t, r):
        called["n"] += 1

    monkeypatch.setattr(commands, "_post_stop_reconcile", _noop_reconcile)
    commands._pending_reconcile_tasks.clear()

    commands._schedule_post_stop_reconcile("s1", "t1", ["r1"])
    # 让出控制权让 task 跑完
    await asyncio.sleep(0.05)
    assert called["n"] == 1
    assert len(commands._pending_reconcile_tasks) == 0


@pytest.mark.asyncio
async def test_schedule_reconcile_noop_on_empty(monkeypatch):
    """无 run_ids 或无 thread_id → 不创建任务。"""
    invoked = {"n": 0}

    async def _should_not_run(s, t, r):
        invoked["n"] += 1

    monkeypatch.setattr(commands, "_post_stop_reconcile", _should_not_run)
    commands._pending_reconcile_tasks.clear()

    commands._schedule_post_stop_reconcile("s1", "t1", [])
    commands._schedule_post_stop_reconcile("s1", None, ["r1"])
    await asyncio.sleep(0.02)
    assert invoked["n"] == 0
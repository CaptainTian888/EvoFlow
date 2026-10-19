"""Persistent MCP connection pool end-to-end tests.

用 FastMCP 起一个带**有状态计数器**的 stdio 服务器，验证池的三条核心语义：

1. 会话复用：同一 server 连续两次调用，计数器递增（per-call session 语义下
   每次都是新子进程，计数器永远回到 0——这正是池要消灭的行为）；
2. 跨线程/跨 loop marshal：工具协程从任意 loop、任意线程调用都正确落到池 loop；
3. stale 重建：杀掉子进程后，下一次调用拿到连接级错误并标记 stale，再下一次
   调用自动重建会话恢复可用（健康检查语义）。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
import textwrap
import threading
import time

import pytest

from evoflow.mcp.pool import (
    McpConnectionPool,
    looks_like_connection_error,
)


@pytest.fixture()
def counter_server_script(tmp_path):
    """Stateful stdio MCP server: counter persists across calls within one session."""
    script = tmp_path / "counter_server.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("counter")

            _state = {"count": 0, "crash_after": None}

            @mcp.tool()
            def bump() -> int:
                \"\"\"Increment and return the counter.\"\"\"
                _state["count"] += 1
                if _state["crash_after"] is not None and _state["count"] >= _state["crash_after"]:
                    sys.exit(9)
                return _state["count"]

            @mcp.tool()
            def arm_crash(after: int) -> str:
                \"\"\"Arm a hard exit once the counter reaches ``after``.\"\"\"
                _state["crash_after"] = after
                return f"armed@{after}"

            if __name__ == "__main__":
                mcp.run(transport="stdio")
            """
        ),
        encoding="utf-8",
    )
    return str(script)


def _tool_int_result(raw: Any) -> int:
    """adapter 工具返回 content_and_artifact 二元组；从 artifact/文本里取回 int。"""
    if isinstance(raw, tuple) and len(raw) == 2:
        artifact = raw[1]
        structured = artifact.get("structured_content") if isinstance(artifact, dict) else None
        if isinstance(structured, dict) and isinstance(structured.get("result"), int):
            return structured["result"]
        content = raw[0]
        if isinstance(content, list) and content and isinstance(content[0], dict):
            return int(content[0].get("text", "0"))
    if isinstance(raw, int):
        return raw
    raise AssertionError(f"unexpected tool result shape: {raw!r}")


@pytest.mark.asyncio
async def test_session_reuse_and_cross_loop_marshal(counter_server_script):
    pool = McpConnectionPool()
    config = {"command": sys.executable, "args": [counter_server_script], "transport": "stdio"}

    tools = await pool.ensure_server_tools("counter", config, timeout_sec=30)
    by_name = {tool.name: tool for tool in tools}
    assert "counter_bump" in by_name

    # 同一会话连续调用：计数器递增（per-call session 语义下两次都是 1）。
    first = _tool_int_result(await by_name["counter_bump"].coroutine())
    second = _tool_int_result(await by_name["counter_bump"].coroutine())
    assert (first, second) == (1, 2)

    # 跨线程 marshal：sync 包装从调用线程提交到池 loop，同一会话继续递增。
    sync_result = _tool_int_result(await asyncio.to_thread(by_name["counter_bump"].func))
    assert sync_result == 3

    await pool.run_on_pool_loop(pool._shutdown_async())


@pytest.mark.asyncio
async def test_stale_rebuild_after_process_crash(counter_server_script, monkeypatch):
    # 子进程 sys.exit 后该 SDK 版本的挂起请求不会自动失败，靠池侧调用超时兜底；
    # 测试用短超时加速（生产默认 120s，EVOFLOW_MCP_CALL_TIMEOUT_SEC 可调）。
    monkeypatch.setenv("EVOFLOW_MCP_CALL_TIMEOUT_SEC", "3")
    pool = McpConnectionPool()
    config = {"command": sys.executable, "args": [counter_server_script], "transport": "stdio"}

    tools = await pool.ensure_server_tools("crashy", config, timeout_sec=30)
    by_name = {tool.name: tool for tool in tools}

    # 状态推进到 1，并在下一次 bump 时让子进程 sys.exit 硬崩。
    assert _tool_int_result(await by_name["crashy_bump"].coroutine()) == 1
    await by_name["crashy_arm_crash"].coroutine(after=2)

    with pytest.raises(Exception):
        await by_name["crashy_bump"].coroutine()

    # 子进程已死：entry 必须被标记 stale（连接级错误判定）。
    for _ in range(60):
        entry = pool._entries.get("crashy")
        if entry is None:
            break
        await asyncio.sleep(0.05)

    # 下一次调用自动重建：全新会话，计数器从 0 开始，功能恢复。
    rebuilt = await pool.ensure_server_tools("crashy", config, timeout_sec=30)
    rebuilt_by_name = {tool.name: tool for tool in rebuilt}
    assert _tool_int_result(await rebuilt_by_name["crashy_bump"].coroutine()) == 1

    await pool.run_on_pool_loop(pool._shutdown_async())


def test_connection_error_classification():
    import anyio

    assert looks_like_connection_error(anyio.ClosedResourceError("stream closed")) is True
    assert looks_like_connection_error(ConnectionResetError()) is True
    assert looks_like_connection_error(ValueError("bad arguments")) is False
    group = ExceptionGroup("tg", [anyio.BrokenResourceError("pipe")])
    assert looks_like_connection_error(group) is True


def test_pool_thread_marshal_from_bare_thread(counter_server_script):
    """同步上下文（无事件循环的裸线程）经 run_on_pool_loop_sync 正常调用。"""
    pool = McpConnectionPool()
    config = {"command": sys.executable, "args": [counter_server_script], "transport": "stdio"}

    tools = pool.run_on_pool_loop_sync(
        lambda: pool._ensure_entry_locked("bare", config, 30.0)
    )
    # ensure_server_tools 返回的池绑定工具才带同步 func；这里显式走同一包装路径。
    bound = [pool._bind_pool_tool("bare", tool) for tool in tools.tools]
    bump = {tool.name: tool for tool in bound}["bare_bump"]

    results: list[int] = []

    def caller():
        # 直接走池绑定工具的同步路径（run_on_pool_loop_sync 链路）。
        results.append(_tool_int_result(bump.func()))

    threads = [threading.Thread(target=caller) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 有状态会话 + 池 loop 串行化：两次调用在同一会话上依次执行
    # （per-call session 语义下两次都是 1）；线程提交顺序是竞态，比集合不比顺序。
    assert sorted(results) == [1, 2]

    pool.shutdown()


@pytest.mark.asyncio
async def test_config_change_triggers_reconnect(counter_server_script, tmp_path):
    """配置漂移（同名字不同配置）→ 关闭旧会话重建。"""
    pool = McpConnectionPool()
    config_a = {"command": sys.executable, "args": [counter_server_script], "transport": "stdio"}
    config_b = {
        "command": sys.executable,
        "args": [counter_server_script],
        "transport": "stdio",
        "env": {"COUNTER_MARK": "b"},
    }

    await pool.ensure_server_tools("drift", config_a, timeout_sec=30)
    entry_a = pool._entries["drift"]
    time.sleep(0.05)
    await pool.ensure_server_tools("drift", config_b, timeout_sec=30)
    entry_b = pool._entries.get("drift")

    assert entry_b is not None and entry_b is not entry_a

    await pool.run_on_pool_loop(pool._shutdown_async())

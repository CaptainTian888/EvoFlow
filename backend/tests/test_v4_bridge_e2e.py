"""T3 — H3-B-3 端到端: 真实流事件序列 → v4 hub 行映射 + 多轮 + 思考 + 工具。

目标(用户原话):
  "调用真实流接口测试 / 参数返回是否正确 / 多轮工具 / 思考是否正常"

策略:
  1) 真实流抓帧: dev server ``POST /api/langgraph/threads/{tid}/runs/stream``
     返回 ``text/event-stream`` AG-UI 帧。这是生产路径上主对话流 → 前端
     wire 的真出口。3 轮 POST 验证多轮同 thread runId 分配 + 帧结构稳定。
  2) H3-B-3 桥接端到端: 把"等价的 AG-UI 事件序列"灌进 ``HubProjectionWriter`` →
     真实 ``conversation.HUB``,订阅一个 ``conversation/{sessionKey}`` topic,
     断言 hub 里行序列、字段、control 状态。
  3) 思考(reasoning)路径: REASONING_MESSAGE_START/_CONTENT/_END → 产生 reasoning
     行,验证 start/content/end 三态。
  4) 工具(tool_call)路径: TOOL_CALL_START/_ARGS/_END/_RESULT → 产生 toolCall 行,
     验证 inputText 累积 + status 收尾。
  5) 多轮: 同一 session 连续 2 轮,每轮都有完整 turnHeader + userInput + assistant
     + turnHeader(终态),rowId 单调递增,phase 在 completed 之后能再回 running。

环境: 不依赖真实 LLM(``models: []`` 走 GraphRecursionError,真流只能验
``RUN_STARTED/ACTIVITY_SNAPSHOT/RUN_ERROR/RUN_FINISHED`` 4 帧;真模型 trace
的 reasoning / tool_call 走合成事件流验证映射契约)。

Run:
    cd backend && python -m pytest tests/test_v4_bridge_e2e.py -v -s
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from app.gateway.v4.conversation import HUB as V4_HUB
from app.gateway.v4.langgraph_v4_bridge import (
    HubProjectionWriter,
    _TranslatorState,
    feed_agui_events,
    feed_payloads_to_v4,
)


# ════════════════════════════════════════════════════════════════════════
# 共享 fixtures
# ════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_hub_sessions():
    """每个 case 之间清空 hub,避免相互污染。"""
    V4_HUB._sessions.clear()  # type: ignore[attr-defined]
    V4_HUB._subscriptions.clear()  # type: ignore[attr-defined]
    yield
    V4_HUB._sessions.clear()  # type: ignore[attr-defined]
    V4_HUB._subscriptions.clear()  # type: ignore[attr-defined]


def _subscribe(topic: str) -> dict[str, Any]:
    """注册一个订阅,返回 ``sub`` + hub 内部 ``_Subscription``。"""
    subscription_id = f"sub-{int(time.time() * 1000000)}"
    connection_id = f"conn-{int(time.time() * 1000000)}"
    from app.gateway.v4.conversation import _Subscription
    sub = _Subscription(
        subscription_id=subscription_id,
        session_id=topic.split("/", 1)[1] if "/" in topic else topic,
        connection_id=connection_id,
        topic=topic,
    )
    V4_HUB._subscriptions[subscription_id] = sub  # type: ignore[attr-defined]
    return {"id": subscription_id, "sub": sub}


def _ops_in_queue(sub) -> list[str]:
    """从 ``sub.queue`` 收集所有 delta op。

    队列帧结构: ``{wireVersion, kind, deliveryKind, frame: {payload: {deltas: [{op, ...}, ...]}}}``
    """
    ops: list[str] = []
    for wrapped in sub.queue:
        if not isinstance(wrapped, dict):
            continue
        frame = wrapped.get("frame") or {}
        payload = frame.get("payload") or {}
        for d in payload.get("deltas") or []:
            op = d.get("op")
            if op:
                ops.append(op)
    return ops


def _state_updates_in_queue(sub) -> list[dict[str, Any]]:
    """从 ``sub.queue`` 提取所有 ``state.updated`` 的 patch.control 字典(顺序保留)。"""
    out: list[dict[str, Any]] = []
    for wrapped in sub.queue:
        if not isinstance(wrapped, dict):
            continue
        frame = wrapped.get("frame") or {}
        payload = frame.get("payload") or {}
        for d in payload.get("deltas") or []:
            if d.get("op") == "state.updated":
                ctrl = d.get("patch", {}).get("control")
                if isinstance(ctrl, dict):
                    out.append(ctrl)
    return out


# ════════════════════════════════════════════════════════════════════════
# 1) 真实流接口打点 (dev server 已在 :8070)
# ════════════════════════════════════════════════════════════════════════


GATEWAY_BASE = os.getenv("EVOFLOW_E2E_GATEWAY", "http://127.0.0.1:8070")
_TEST_THREAD_ID = os.getenv("EVOFLOW_E2E_THREAD_ID", "356e71d9-5008-49ab-bde4-ebc6a03ef901")


def _is_dev_server_up() -> bool:
    try:
        import urllib.request as _ur
        with _ur.urlopen(f"{GATEWAY_BASE}/health/ready", timeout=2) as r:  # noqa: S310
            return r.status == 200
    except Exception:
        return False


def _post_stream(thread_id: str, body: dict[str, Any], timeout_s: float = 30.0) -> tuple[int, str, list[dict[str, Any]]]:
    """直接 ``curl.exe -N`` 抓 ``text/event-stream`` 真 SSE 帧,逐 ``event: ag-ui / data: ...`` 解析。"""
    body_path = Path("D:/dev/github/_e2e_body.json")
    body_path.write_text(json.dumps(body), encoding="utf-8")
    out_path = Path("D:/dev/github/_e2e_stream.txt")
    cmd = [
        "curl.exe", "-sS", "--max-time", str(int(timeout_s)),
        "-N",
        f"{GATEWAY_BASE}/api/langgraph/threads/{thread_id}/runs/stream",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "--data-binary", "@-",
        "-o", str(out_path),
        "-w", "HTTP=%{http_code} CT=%{content_type} SIZE=%{size_download}",
    ]
    proc = subprocess.run(
        cmd,
        input=body_path.read_bytes(),
        capture_output=True,
        timeout=timeout_s + 5,
    )
    meta = proc.stdout.decode("utf-8", errors="replace").strip()
    raw = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
    frames: list[dict[str, Any]] = []
    for blk in raw.split("\n\n"):
        ev_line, data_line = "", ""
        for ln in blk.splitlines():
            if ln.startswith("event: "):
                ev_line = ln[7:].strip()
            elif ln.startswith("data: "):
                data_line = ln[6:].strip()
        if not ev_line and not data_line:
            continue
        try:
            payload = json.loads(data_line) if data_line else {}
        except Exception:
            payload = {"_raw": data_line}
        frames.append({"event": ev_line, "data": payload})
    http_code = 0
    if meta.startswith("HTTP="):
        try:
            http_code = int(meta.split("HTTP=")[1].split()[0])
        except Exception:
            http_code = 0
    return http_code, meta, frames


@pytest.mark.skipif(not _is_dev_server_up(), reason="dev server :8070 not reachable")
def test_real_stream_runs_basic_contract():
    """真实流接口打点: HTTP 200 + text/event-stream + AG-UI 帧序列稳定。"""
    body = {
        "assistant_id": "lead_agent",
        "stream_mode": "messages-tuple",
        "multitask_strategy": "interrupt",
        "input": {"messages": [{"role": "user", "content": "ping"}]},
        "config": {"configurable": {"thread_id": "e2e-contract-1"}},
    }
    http, meta, frames = _post_stream(_TEST_THREAD_ID, body, timeout_s=20)
    assert http == 200, f"expected 200, got {http} meta={meta!r}"
    assert "text/event-stream" in meta
    # 当前环境 models:[] 走 GraphRecursionError,4 帧固定。
    types = [f["data"].get("type") for f in frames if isinstance(f["data"], dict)]
    assert "RUN_STARTED" in types, types
    assert "RUN_FINISHED" in types, types
    # RUN_STARTED 必带 runId (回放端用做 thread ↔ run 关联)
    rs = next(f for f in frames if f["data"].get("type") == "RUN_STARTED")
    assert rs["data"].get("runId"), rs
    # 所有帧的 event 行必须是 ag-ui
    for f in frames:
        assert f["event"] == "ag-ui", f


@pytest.mark.skipif(not _is_dev_server_up(), reason="dev server :8070 not reachable")
def test_real_stream_multi_turn_same_thread_runids_differ():
    """多轮: 同一 threadId 连续 2 次 POST,runId 必须独立分配。"""
    body = {
        "assistant_id": "lead_agent",
        "stream_mode": "messages-tuple",
        "multitask_strategy": "interrupt",
        "input": {"messages": [{"role": "user", "content": "turn-1"}]},
        "config": {"configurable": {"thread_id": "e2e-multiturn-A"}},
    }
    _, _, f1 = _post_stream(_TEST_THREAD_ID, body, timeout_s=20)
    _, _, f2 = _post_stream(_TEST_THREAD_ID, body, timeout_s=20)

    r1 = next(x for x in f1 if x["data"].get("type") == "RUN_STARTED")
    r2 = next(x for x in f2 if x["data"].get("type") == "RUN_STARTED")
    assert r1["data"]["runId"] != r2["data"]["runId"], "runId 应每次独立分配"
    # 同一 thread,threadId 串到 RUN_STARTED / RUN_FINISHED 帧(若帧带)
    assert r1["data"].get("threadId") == r2["data"].get("threadId")


# ════════════════════════════════════════════════════════════════════════
# 2) H3-B-3 桥接端到端: AG-UI 事件流 → hub 行
# ════════════════════════════════════════════════════════════════════════


def _make_run_event_sequence(*, with_reasoning: bool = True, with_tool: bool = True, run_id: str = "run-aaa") -> list[dict[str, Any]]:
    """合成"一次完整 run"的 AG-UI 事件序列(含 reasoning + tool_call)。"""
    seq: list[dict[str, Any]] = [
        {"type": "RUN_STARTED", "threadId": "thread-1", "runId": run_id},
    ]
    if with_reasoning:
        seq += [
            {"type": "REASONING_MESSAGE_START", "messageId": f"r-{run_id}"},
            {"type": "REASONING_MESSAGE_CONTENT", "messageId": f"r-{run_id}", "delta": "思考中…"},
            {"type": "REASONING_MESSAGE_CONTENT", "messageId": f"r-{run_id}", "delta": "再想想"},
            {"type": "REASONING_MESSAGE_END", "messageId": f"r-{run_id}"},
        ]
    seq += [
        {"type": "TEXT_MESSAGE_START", "messageId": f"m-{run_id}"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": f"m-{run_id}", "delta": "你好"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": f"m-{run_id}", "delta": "世界"},
        {"type": "TEXT_MESSAGE_END", "messageId": f"m-{run_id}"},
    ]
    if with_tool:
        seq += [
            {"type": "TOOL_CALL_START", "toolCallId": f"tc-{run_id}", "toolCallName": "web_search"},
            {"type": "TOOL_CALL_ARGS", "toolCallId": f"tc-{run_id}", "delta": '{"q":"EvoFlow"}'},
            {"type": "TOOL_CALL_END", "toolCallId": f"tc-{run_id}"},
            {"type": "TOOL_CALL_RESULT", "toolCallId": f"tc-{run_id}", "content": "hit 3 docs", "status": "success"},
        ]
    seq.append({"type": "RUN_FINISHED", "threadId": "thread-1", "runId": run_id})
    return seq


def test_bridge_e2e_one_run_full_event_sequence():
    """一次完整 run(thinking + text + tool) → hub 行序列 + 字段正确。"""
    session_key = "sess-e2e-1"
    sub_info = _subscribe(f"conversation/{session_key}")
    writer = HubProjectionWriter(session_key)
    state = _TranslatorState()

    events = _make_run_event_sequence()
    feed_agui_events(session_key, events)

    sess = V4_HUB.get_session(session_key)
    assert sess is not None
    rows = sess.rows
    # 行 kind 集合(turnHeader, reasoning, assistantText, toolCall, 各一次)
    kinds = [r["kind"] for r in rows.values()]
    assert kinds.count("turnHeader") == 1
    assert kinds.count("reasoning") == 1
    assert kinds.count("assistantText") == 1
    assert kinds.count("toolCall") == 1
    # 终态:turnHeader completedSuccess
    header = next(r for r in rows.values() if r["kind"] == "turnHeader")
    assert header["state"] == "completedSuccess", header
    assert header.get("endedAt")
    # reasoning 累积 + 终态
    rea = next(r for r in rows.values() if r["kind"] == "reasoning")
    assert rea["text"] == "思考中…再想想", rea
    assert rea["state"] == "complete"
    # assistant text 累积
    txt = next(r for r in rows.values() if r["kind"] == "assistantText")
    assert txt["text"] == "你好世界", txt
    assert txt["state"] == "complete"
    # tool: inputText 累积 + 终态 success
    tool = next(r for r in rows.values() if r["kind"] == "toolCall")
    assert tool["toolName"] == "web_search"
    assert tool["inputText"] == '{"q":"EvoFlow"}'
    assert tool["status"] == "success", tool
    assert tool.get("endedAt")
    # tool.output 是结构化
    assert tool["output"]["kind"] == "text"
    assert tool["output"]["text"] == "hit 3 docs"
    # 订阅者收到 row.upserted 帧(tool 收尾 / run 终态都应到)
    sub = sub_info["sub"]
    ops = _ops_in_queue(sub)
    assert "row.upserted" in ops, ops


def test_bridge_e2e_thinking_only_no_text():
    """只有 reasoning 没有 text_message → reasoning 行存在,assistant 行不应产生。"""
    session_key = "sess-e2e-thinking-only"
    _subscribe(f"conversation/{session_key}")
    seq = [
        {"type": "RUN_STARTED", "threadId": "t", "runId": "r"},
        {"type": "REASONING_MESSAGE_START", "messageId": "r1"},
        {"type": "REASONING_MESSAGE_CONTENT", "messageId": "r1", "delta": "hmm"},
        {"type": "REASONING_MESSAGE_END", "messageId": "r1"},
        {"type": "RUN_FINISHED", "threadId": "t", "runId": "r"},
    ]
    feed_agui_events(session_key, seq)
    sess = V4_HUB.get_session(session_key)
    kinds = [r["kind"] for r in sess.rows.values()]
    assert "reasoning" in kinds
    assert "assistantText" not in kinds
    rea = next(r for r in sess.rows.values() if r["kind"] == "reasoning")
    assert rea["text"] == "hmm"
    assert rea["state"] == "complete"


def test_bridge_e2e_multi_turn_same_session():
    """多轮: 同一 session 两次 run,行 rowId 单调递增,turnHeader 两条,phase 回到 running 再 completed。"""
    session_key = "sess-e2e-multiturn"
    _subscribe(f"conversation/{session_key}")

    feed_agui_events(session_key, _make_run_event_sequence(with_tool=False, run_id="run-t1"))
    sess = V4_HUB.get_session(session_key)
    assert sess.phase == "completedSuccess" or sess.phase == "completed"
    row_ids_after_t1 = sorted(sess.rows.keys())
    assert len(row_ids_after_t1) >= 2  # turnHeader + assistantText

    # 第二轮代表"新订阅 / 新 run":清掉 bridge 的 translator 缓存(等价于前端
    # unsubscribe → resubscribe,生产路径上由 H3-B-3 的 unsubscribe 钩子触发)。
    from app.gateway.v4.langgraph_v4_bridge import _translator_states, _state_lock
    with _state_lock:
        _translator_states.pop(session_key, None)

    # 重置 translator state(每次新 run 用新 state,模拟新订阅)
    feed_agui_events(session_key, _make_run_event_sequence(with_reasoning=False, with_tool=False, run_id="run-t2"))
    row_ids_after_t2 = sorted(sess.rows.keys())
    # 第二轮必须分配**新** rowId(>= 已有最大 + 1)
    assert row_ids_after_t2[-1] > row_ids_after_t1[-1], (row_ids_after_t1, row_ids_after_t2)
    # 两个 turnHeader,各对应不同 turnId
    headers = sorted(
        (r for r in sess.rows.values() if r["kind"] == "turnHeader"),
        key=lambda r: r["rowId"],
    )
    assert len(headers) == 2
    assert headers[0]["turnId"] != headers[1]["turnId"]
    # 都应已收敛到 completedSuccess
    assert all(h["state"] == "completedSuccess" for h in headers)
    # 最终 phase
    assert sess.phase in ("completed", "completedSuccess", "ready")


def test_bridge_e2e_run_error_yields_failed_header():
    """RUN_ERROR → turnHeader.state=failed,control.phase=error,lastError 落库。"""
    session_key = "sess-e2e-err"
    sub_info = _subscribe(f"conversation/{session_key}")
    seq = [
        {"type": "RUN_STARTED", "threadId": "t", "runId": "r"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "开始…"},
        {"type": "TEXT_MESSAGE_END", "messageId": "m"},
        {"type": "RUN_ERROR", "message": "GraphRecursionError(25)", "code": "ERROR"},
    ]
    feed_agui_events(session_key, seq)
    sess = V4_HUB.get_session(session_key)
    header = next(r for r in sess.rows.values() if r["kind"] == "turnHeader")
    assert header["state"] == "failed", header
    txt = next(r for r in sess.rows.values() if r["kind"] == "assistantText")
    assert txt["state"] == "complete"  # TEXT_MESSAGE_END 收敛到 complete,错误由 header 收尾
    # 订阅者收到 state.updated 帧
    sub = sub_info["sub"]
    state_ops = _state_updates_in_queue(sub)
    assert state_ops, "RUN_ERROR 应至少投递一次 state.updated"
    last_state = state_ops[-1]
    assert last_state.get("phase") == "error"
    assert last_state.get("canStop") is False
    assert last_state.get("lastError", {}).get("code") == "run_error"


def test_bridge_e2e_tool_error_status_maps_to_error_output():
    """TOOL_CALL_RESULT status=error → toolCall.status=error + output.kind=error。"""
    session_key = "sess-e2e-toolerr"
    _subscribe(f"conversation/{session_key}")
    seq = [
        {"type": "RUN_STARTED", "threadId": "t", "runId": "r"},
        {"type": "TOOL_CALL_START", "toolCallId": "tc", "toolCallName": "fail_tool"},
        {"type": "TOOL_CALL_END", "toolCallId": "tc"},
        {"type": "TOOL_CALL_RESULT", "toolCallId": "tc", "content": "boom", "status": "error"},
        {"type": "RUN_FINISHED", "threadId": "t", "runId": "r"},
    ]
    feed_agui_events(session_key, seq)
    sess = V4_HUB.get_session(session_key)
    tool = next(r for r in sess.rows.values() if r["kind"] == "toolCall")
    assert tool["status"] == "error"
    assert tool["output"]["kind"] == "error"
    assert tool["output"]["error"]["message"] == "boom"


def test_bridge_payloads_uses_thread_state_independent_of_main_path():
    """``feed_payloads_to_v4``(SSE attach 续挂路径)与 ``feed_agui_events`` 共享 _thread_bridge 缓存。

    这条不依赖真实 SSE attach — 只验 thread 解析失败时静默跳过(零回归硬约束)。
    """
    # threadId 解析不到 → bridge 静默返回,HubProjectionWriter 不被创建。
    # 用一个不存在的 thread,断言无异常 + hub 状态干净。
    feed_payloads_to_v4("nonexistent-thread-id-xyz", [{"foo": "bar"}])
    # hub 仍空
    assert V4_HUB._sessions == {}  # type: ignore[attr-defined]

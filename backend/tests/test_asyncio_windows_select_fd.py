"""Windows SelectorEventLoop FD soft-limit helpers (select FD_SETSIZE≈512)."""

from __future__ import annotations

import types

import pytest

from evoflow.platform import asyncio_windows as aw


def test_is_windows_select_fd_exhaustion_error_detects_value_error():
    exc = ValueError("too many file descriptors in select()")
    assert aw.is_windows_select_fd_exhaustion_error(exc) is True


def test_is_windows_select_fd_exhaustion_error_walks_context():
    inner = ValueError("too many file descriptors in select()")
    outer = RuntimeError("loop failed")
    outer.__cause__ = inner
    assert aw.is_windows_select_fd_exhaustion_error(outer) is True
    assert aw.is_windows_select_fd_exhaustion_error(RuntimeError("other")) is False
    assert aw.is_windows_select_fd_exhaustion_error(None) is False


def test_windows_selector_recommended_limit_concurrency_caps_under_fd_setsize(monkeypatch):
    monkeypatch.setattr(aw.sys, "platform", "win32")
    monkeypatch.setenv("EVOFLOW_WIN_SELECTOR_EVENT_LOOP", "1")
    monkeypatch.delenv("EVOFLOW_WIN_LIMIT_CONCURRENCY", raising=False)
    limit = aw.windows_selector_recommended_limit_concurrency()
    assert limit is not None
    assert 32 <= limit <= aw.windows_selector_fd_soft_limit() - 64


def test_windows_selector_recommended_limit_respects_env_override(monkeypatch):
    monkeypatch.setattr(aw.sys, "platform", "win32")
    monkeypatch.setenv("EVOFLOW_WIN_SELECTOR_EVENT_LOOP", "1")
    monkeypatch.setenv("EVOFLOW_WIN_LIMIT_CONCURRENCY", "200")
    assert aw.windows_selector_recommended_limit_concurrency() == 200


def test_windows_selector_recommended_limit_none_when_selector_disabled(monkeypatch):
    monkeypatch.setattr(aw.sys, "platform", "win32")
    monkeypatch.setenv("EVOFLOW_WIN_SELECTOR_EVENT_LOOP", "0")
    assert aw.windows_selector_recommended_limit_concurrency() is None


def test_apply_windows_uvicorn_concurrency_limit(monkeypatch):
    monkeypatch.setattr(aw.sys, "platform", "win32")
    monkeypatch.setenv("EVOFLOW_WIN_SELECTOR_EVENT_LOOP", "1")
    monkeypatch.setenv("EVOFLOW_WIN_LIMIT_CONCURRENCY", "250")
    config = types.SimpleNamespace(limit_concurrency=None)
    applied = aw.apply_windows_uvicorn_concurrency_limit(config)
    assert applied == 250
    assert config.limit_concurrency == 250


def test_run_uvicorn_guard_exits_on_select_fd_exhaustion(monkeypatch):
    monkeypatch.setattr(aw.sys, "platform", "win32")

    def boom():
        raise ValueError("too many file descriptors in select()")

    with pytest.raises(SystemExit) as ei:
        aw.run_uvicorn_with_windows_shutdown_guard(boom)
    assert ei.value.code == 75


def test_startup_gate_loading_extended_retry_after_is_slower():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.gateway.startup_gate import StartupGateMiddleware

    app = FastAPI()
    app.state._is_evoflow_gateway_app = True
    app.state.routers_registered = True
    app.state.extended_routers_registered = False
    app.add_middleware(StartupGateMiddleware)

    @app.get("/api/proactive/roles")
    def roles():
        return {"roles": []}

    client = TestClient(app)
    resp = client.get("/api/proactive/roles")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "loading_extended"
    assert int(body["retry_after_ms"]) >= 2000

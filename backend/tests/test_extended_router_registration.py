"""Regression: one missing extended router must not brick loading_extended forever."""

from __future__ import annotations

import importlib

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.gateway.router_registry import _include_module_router
from app.gateway.startup_gate import StartupGateMiddleware


def test_optional_include_missing_module_returns_false_without_raise():
    app = FastAPI()
    ok = _include_module_router(
        app,
        "app.gateway.__missing_extended_router_for_test__",
        label="missing",
        optional=True,
    )
    assert ok is False


def test_required_include_missing_module_raises():
    app = FastAPI()
    with pytest.raises(ModuleNotFoundError):
        _include_module_router(
            app,
            "app.gateway.__missing_extended_router_for_test__",
            label="missing",
            optional=False,
        )


def test_optional_failure_does_not_block_later_mount(monkeypatch):
    """Simulate packaged build missing app.gateway.v4 while later routers exist."""
    import types

    app = FastAPI()
    later = APIRouter()

    @later.get("/api/apps")
    def _apps():
        return {"ok": True}

    real_import = importlib.import_module

    def fake_import(name, package=None):
        if name == "app.gateway.v4.routes":
            raise ModuleNotFoundError(name)
        if name == "app.gateway.routers._test_later_apps":
            m = types.ModuleType(name)
            m.router = later
            return m
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    assert (
        _include_module_router(
            app,
            "app.gateway.v4.routes",
            label="v4_sessions",
            optional=True,
            include_in_schema=False,
        )
        is False
    )
    assert (
        _include_module_router(
            app,
            "app.gateway.routers._test_later_apps",
            label="apps",
            optional=True,
        )
        is True
    )

    client = TestClient(app)
    assert client.get("/api/apps").json() == {"ok": True}


def test_startup_gate_clears_loading_extended_when_flag_set():
    app = FastAPI()
    app.state._is_evoflow_gateway_app = True
    app.state.routers_registered = True
    app.state.extended_routers_registered = False
    app.add_middleware(StartupGateMiddleware)

    @app.get("/api/proactive/roles")
    def roles():
        return {"roles": []}

    client = TestClient(app)
    blocked = client.get("/api/proactive/roles")
    assert blocked.status_code == 503
    assert blocked.json()["error"] == "loading_extended"

    app.state.extended_routers_registered = True
    # Middleware already constructed; flag is read from app.state each request.
    ok = client.get("/api/proactive/roles")
    assert ok.status_code == 200
    assert ok.json() == {"roles": []}

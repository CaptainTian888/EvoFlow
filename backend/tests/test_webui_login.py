"""Regression tests for WebUI login error contract.

Covers task 2608090142_573c / rework 2608090441_509c:
* ``POST /api/webui/login`` returns **400** for malformed parameters
  (empty / whitespace-only username or password) — a client parameter error
  that must never surface as a 500.
* Credential mismatch (well-formed but wrong password) stays **401**.

The webui router module is loaded directly by file path via ``importlib`` to
bypass ``app.gateway.routers.__init__`` (which bulk-imports every sub-router
and can trip the conftest executor mock). This keeps the regression isolated
to the login endpoint's pure logic.

Run: cd backend && python -m pytest tests/test_webui_login.py -v
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_WEBUI_PATH = (
    _BACKEND_ROOT / "app" / "gateway" / "routers" / "webui.py"
)


# ── Load webui router by file path (bypass routers/__init__) ─


def _load_webui_module():
    if _WEBUI_PATH in sys.modules:
        return sys.modules[_WEBUI_PATH]
    spec = importlib.util.spec_from_file_location(
        "webui_login_regression", _WEBUI_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["webui_login_regression"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def webui_module():
    return _load_webui_module()


# ── malformed-parameter detection (→ 400) ────────────────────


class TestMalformedParams:
    def test_empty_username_is_malformed(self, webui_module):
        assert webui_module._login_params_are_malformed("", "secret") is not None

    def test_whitespace_username_is_malformed(self, webui_module):
        assert webui_module._login_params_are_malformed("   ", "secret") is not None

    def test_empty_password_is_malformed(self, webui_module):
        assert webui_module._login_params_are_malformed("admin", "") is not None

    def test_whitespace_password_is_malformed(self, webui_module):
        assert webui_module._login_params_are_malformed("admin", "   ") is not None

    def test_well_formed_params_pass(self, webui_module):
        assert webui_module._login_params_are_malformed("admin", "secret") is None


# ── 400 vs 401 status mapping on the login endpoint ──────────


import asyncio


def _run(coro):
    """Run an async coroutine synchronously for the login endpoint tests."""
    return asyncio.run(coro)


class TestLoginStatusMapping:
    @pytest.fixture()
    def webui(self, webui_module, monkeypatch):
        monkeypatch.setattr(
            webui_module, "verify_user_credentials", lambda u, p: None
        )
        return webui_module

    def test_malformed_params_raise_400(self, webui):
        body = type("B", (), {"username": "", "password": "x"})()
        with pytest.raises(webui.HTTPException) as ei:
            _run(webui.login(body))
        assert ei.value.status_code == 400

    def test_whitespace_password_raises_400(self, webui):
        body = type("B", (), {"username": "admin", "password": "   "})()
        with pytest.raises(webui.HTTPException) as ei:
            _run(webui.login(body))
        assert ei.value.status_code == 400

    def test_credential_mismatch_raises_401(self, webui):
        body = type("B", (), {"username": "admin", "password": "wrongpass"})()
        with pytest.raises(webui.HTTPException) as ei:
            _run(webui.login(body))
        assert ei.value.status_code == 401


# ── baseline sanity: well-formed creds → token (no 500) ─────


class TestLoginBaseline:
    def test_login_returns_jwt_for_valid_creds(self, webui_module, monkeypatch):
        fake_user = {"id": 1, "username": "admin", "is_primary": 1}
        monkeypatch.setattr(
            webui_module, "verify_user_credentials", lambda u, p: fake_user
        )
        monkeypatch.setattr(
            webui_module, "generate_jwt", webui_module.generate_jwt
        )
        body = type("B", (), {"username": "admin", "password": "secret"})()
        resp = _run(webui_module.login(body))
        assert resp.token
        assert resp.username == "admin"

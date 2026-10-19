"""Tests for multi-user WebUI login (verify_user_credentials)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_AUTH_PATH = _BACKEND_ROOT / "packages" / "harness" / "evoflow" / "webui" / "auth.py"


def _load_auth_module():
    name = "webui_auth_user_credentials_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _AUTH_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def webui_auth():
    return _load_auth_module()


class TestVerifyUserCredentials:
    def test_delegates_to_db_lookup(self, webui_auth, monkeypatch):
        fake_row = {"id": 2, "username": "alice", "password_hash": "h", "is_primary": 0}

        def fake_execute(sql, params):
            assert "username = ?" in sql
            assert params == ("alice",)

            class Cur:
                def fetchone(self_inner):
                    return fake_row

            return Cur()

        def fake_get_db():
            class Db:
                def execute(self, sql, params):
                    return fake_execute(sql, params)

            return Db()

        monkeypatch.setattr(webui_auth, "get_db", fake_get_db)
        monkeypatch.setattr(webui_auth, "verify_password", lambda pw, h: pw == "secret" and h == "h")

        import evoflow.authz.principals as principals_mod

        monkeypatch.setattr(principals_mod, "resolve_principal_by_identity", lambda *a, **k: {"status": "active"})

        user = webui_auth.verify_user_credentials("alice", "secret")
        assert user is not None
        assert user["username"] == "alice"

    def test_rejects_deactivated_principal(self, webui_auth, monkeypatch):
        fake_row = {"id": 3, "username": "bob", "password_hash": "h", "is_primary": 0}

        monkeypatch.setattr(
            webui_auth,
            "get_db",
            lambda: type(
                "Db",
                (),
                {
                    "execute": lambda self, sql, params: type(
                        "Cur",
                        (),
                        {"fetchone": lambda self: fake_row},
                    )()
                },
            )(),
        )
        monkeypatch.setattr(webui_auth, "verify_password", lambda pw, h: True)

        import evoflow.authz.principals as principals_mod

        monkeypatch.setattr(
            principals_mod,
            "resolve_principal_by_identity",
            lambda *a, **k: {"status": "deactivated"},
        )

        assert webui_auth.verify_user_credentials("bob", "secret") is None

    def test_wrong_password_returns_none(self, webui_auth, monkeypatch):
        fake_row = {"id": 1, "username": "admin", "password_hash": "h", "is_primary": 1}

        monkeypatch.setattr(
            webui_auth,
            "get_db",
            lambda: type(
                "Db",
                (),
                {
                    "execute": lambda self, sql, params: type(
                        "Cur",
                        (),
                        {"fetchone": lambda self: fake_row},
                    )()
                },
            )(),
        )
        monkeypatch.setattr(webui_auth, "verify_password", lambda pw, h: False)

        assert webui_auth.verify_user_credentials("admin", "wrong") is None

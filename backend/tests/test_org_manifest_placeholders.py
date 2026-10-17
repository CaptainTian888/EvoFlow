"""回归：组织包占位符（曾因 manifest.py 缺 import os 而全量安装回滚）。"""

from __future__ import annotations

from evoflow.organizations.manifest import apply_placeholders, deep_apply_placeholders


def test_apply_placeholders_resolves_evoflow_home(monkeypatch) -> None:
    monkeypatch.setenv("EVOFLOW_HOME", "C:/fake-home")
    out = apply_placeholders("home=${EVOFLOW_HOME} ws=${ORG_WORKSPACE} root=${ORG_ROOT}", org_workspace="D:/ws", org_root="D:/pack")
    assert out == "home=C:/fake-home ws=D:/ws root=D:/pack"


def test_deep_apply_placeholders_walks_nested(monkeypatch) -> None:
    monkeypatch.setenv("EVOFLOW_HOME", "C:/fake-home")
    payload = {
        "config": {
            "workspace_path": ["${ORG_WORKSPACE}"],
            "nested": {"p": "${ORG_ROOT}/x"},
        },
        "keep": 3,
    }
    out = deep_apply_placeholders(payload, org_workspace="D:/ws", org_root="D:/pack")
    assert out["config"]["workspace_path"] == ["D:/ws"]
    assert out["config"]["nested"]["p"] == "D:/pack/x"
    assert out["keep"] == 3

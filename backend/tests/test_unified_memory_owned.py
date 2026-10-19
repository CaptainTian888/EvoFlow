"""Tests for unified mem_* memory on Owned KB."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def owned_memory_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOFLOW_KNOWLEDGE_ROOT", str(root))
    monkeypatch.setenv("EVOFLOW_HOME", str(tmp_path))
    from evoflow.knowledge.owned.db import reset_db_state_for_tests
    from evoflow.agents.memory.storage import reset_storage_for_tests

    reset_db_state_for_tests()
    reset_storage_for_tests()
    yield root
    reset_db_state_for_tests()
    reset_storage_for_tests()


def test_remember_recall_get_core(owned_memory_root: Path):
    from evoflow.memory.facade import get_core, recall, remember
    from evoflow.memory.namespaces import agent_ns

    ns = agent_ns("main")
    aid = remember(
        ns,
        "用户偏好使用 Python 做后端",
        layer="semantic",
        kind="preference",
        confidence=0.9,
        importance=0.9,
        pin=True,
        source="manual",
        subject_key="pref.language",
    )
    assert aid
    remember(
        ns,
        "上周完成了支付 API 重构，结论是拆分 webhook 校验",
        layer="episodic",
        kind="episode",
        confidence=0.85,
        importance=0.8,
        source="manual",
    )
    core = get_core([ns], max_chars=2000)
    assert any("Python" in (a.get("content") or "") for a in core)
    hits = recall([ns], "支付 API 重构", top_k=5, max_chars=2000)
    assert hits
    assert any("webhook" in (a.get("content") or "") for a in hits)


def test_storage_document_roundtrip(owned_memory_root: Path):
    from evoflow.agents.memory.storage import create_empty_memory, get_memory_storage

    storage = get_memory_storage()
    doc = create_empty_memory()
    doc["user"]["workContext"] = {"summary": "后端工程师", "updatedAt": ""}
    doc["facts"] = [
        {
            "id": "fact-1",
            "content": "喜欢简洁的提交信息",
            "category": "preference",
            "confidence": 0.9,
        }
    ]
    assert storage.save(doc, "main")
    loaded = storage.reload("main")
    assert "后端工程师" in (loaded.get("user") or {}).get("workContext", {}).get("summary", "")
    assert any(f.get("content") == "喜欢简洁的提交信息" for f in loaded.get("facts") or [])


def test_person_memory_uses_mem(owned_memory_root: Path):
    from evoflow.persistence import person_memory_repositories as pm

    eid = pm.insert_person_memory(
        "xiaomi",
        "今天值班处理了告警风暴",
        layer="journal",
        importance=0.7,
        source="wrap_up",
        access_tier="archival",
    )
    assert eid
    rows = pm.list_person_memory("xiaomi", limit=10)
    assert any("告警风暴" in (r.get("content") or "") for r in rows)
    got = pm.get_person_memory(eid)
    assert got and "告警风暴" in (got.get("content") or "")

"""Tests for memory consolidate (merge / decay / GC)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture()
def owned_memory_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOFLOW_KNOWLEDGE_ROOT", str(root))
    monkeypatch.setenv("EVOFLOW_HOME", str(tmp_path))
    from evoflow.agents.memory.storage import reset_storage_for_tests
    from evoflow.knowledge.owned.db import reset_db_state_for_tests

    reset_db_state_for_tests()
    reset_storage_for_tests()
    yield root
    reset_db_state_for_tests()
    reset_storage_for_tests()


def test_consolidate_merges_near_duplicate_semantic(owned_memory_root: Path):
    from evoflow.memory.consolidate import consolidate_namespace, text_overlap
    from evoflow.memory.facade import list_atoms, remember
    from evoflow.memory.namespaces import agent_ns
    from evoflow.memory.store import get_atom

    ns = agent_ns("main")
    a = "用户偏好使用 Python 做后端服务开发，并且喜欢简洁的提交信息与清晰的 PR 描述"
    b = "用户偏好使用 Python 做后端服务开发，并且喜欢简洁的提交信息与清晰的PR描述"
    assert text_overlap(a, b) >= 0.85
    id1 = remember(ns, a, layer="semantic", confidence=0.8, importance=0.8, source="manual")
    id2 = remember(ns, b, layer="semantic", confidence=0.9, importance=0.85, source="manual")
    assert id1 and id2 and id1 != id2

    stats = consolidate_namespace(ns, trigger="manual", similarity_merge=0.85)
    assert stats["similarity_merged"] >= 1
    active = list_atoms(ns, layers=["semantic"], limit=50)
    assert len(active) == 1
    dead = get_atom(id1) if id1 != active[0]["id"] else get_atom(id2)
    # soft-deleted atoms are not returned by get_atom
    assert dead is None
    from evoflow.knowledge.owned.db import db

    with db() as conn:
        row = conn.execute(
            "SELECT superseded_by, deleted_at FROM mem_atoms WHERE id IN (?,?)",
            (id1, id2),
        ).fetchall()
        superseded = [r for r in row if r["superseded_by"]]
        assert superseded


def test_consolidate_skips_episodic_fuzzy_merge(owned_memory_root: Path):
    from evoflow.memory.consolidate import consolidate_namespace
    from evoflow.memory.facade import list_atoms, remember
    from evoflow.memory.namespaces import agent_ns

    ns = agent_ns("main")
    text = "完成了支付 API 重构，结论是拆分 webhook 校验与幂等键处理"
    remember(ns, text, layer="episodic", confidence=0.9, source="manual")
    remember(
        ns,
        text + "。补充：加了重试日志",
        layer="episodic",
        confidence=0.9,
        source="manual",
    )
    stats = consolidate_namespace(ns, trigger="manual", similarity_merge=0.5)
    assert stats["similarity_merged"] == 0
    assert len(list_atoms(ns, layers=["episodic"], limit=20)) == 2


def test_consolidate_pin_exempt_from_gc(owned_memory_root: Path):
    from evoflow.knowledge.owned.db import db
    from evoflow.memory.consolidate import consolidate_namespace
    from evoflow.memory.facade import list_atoms, remember
    from evoflow.memory.namespaces import agent_ns

    ns = agent_ns("main")
    pinned = remember(
        ns,
        "必须保留的 pinned 低置信事实",
        layer="semantic",
        confidence=0.2,
        pin=True,
        source="manual",
    )
    doomed = remember(
        ns,
        "可清理的低置信噪声事实",
        layer="semantic",
        confidence=0.2,
        pin=False,
        source="manual",
    )
    assert pinned and doomed
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat().replace("+00:00", "Z")
    with db() as conn:
        conn.execute(
            "UPDATE mem_atoms SET updated_at=?, last_accessed_at=? WHERE id IN (?,?)",
            (old, old, pinned, doomed),
        )

    stats = consolidate_namespace(ns, trigger="manual", gc_min_confidence=0.55, gc_idle_days=30)
    assert stats["gc_deleted"] >= 1
    ids = {a["id"] for a in list_atoms(ns, limit=50)}
    assert pinned in ids
    assert doomed not in ids


def test_consolidate_decays_vitality(owned_memory_root: Path):
    from evoflow.knowledge.owned.db import db
    from evoflow.memory.consolidate import consolidate_namespace
    from evoflow.memory.facade import remember
    from evoflow.memory.namespaces import agent_ns
    from evoflow.memory.store import get_atom

    ns = agent_ns("main")
    aid = remember(
        ns,
        "很久没被召回的普通事实",
        layer="semantic",
        confidence=0.9,
        vitality=1.0,
        source="manual",
    )
    old = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat().replace("+00:00", "Z")
    with db() as conn:
        conn.execute(
            "UPDATE mem_atoms SET updated_at=?, last_accessed_at=? WHERE id=?",
            (old, old, aid),
        )
    stats = consolidate_namespace(ns, trigger="manual", decay_factor=0.92)
    assert stats["decayed"] >= 1
    atom = get_atom(aid)
    assert atom is not None
    assert float(atom["vitality"]) < 1.0

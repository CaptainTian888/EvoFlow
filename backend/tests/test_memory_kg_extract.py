"""Tests for LLM-only mem_kg extract (batch + single; no heuristic fallback)."""

from __future__ import annotations

import asyncio
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


def test_mem_kg_extract_applies_llm_graph(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.knowledge.owned import kg
    from evoflow.memory.facade import remember
    from evoflow.memory.kg_extract import list_atom_entities, mem_kb_id, run_mem_kg_extract
    from evoflow.memory.namespaces import agent_ns

    ns = agent_ns("main")
    monkeypatch.setattr("evoflow.memory.facade._schedule_kg_batch", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_threshold", lambda *_a, **_k: None)
    aid = remember(
        ns,
        "完成了支付 API 重构，结论是拆分 webhook 校验",
        layer="episodic",
        kind="episode",
        confidence=0.9,
        source="manual",
    )
    assert aid

    async def _fake_llm(_atom):
        return {
            "nodes": [
                {"name": "支付 API", "kind": "concept"},
                {"name": "webhook 校验", "kind": "concept"},
            ],
            "edges": [
                {"src": "支付 API", "rel": "RESULTED_IN", "dst": "webhook 校验"},
            ],
        }

    monkeypatch.setattr("evoflow.memory.kg_extract.extract_graph_llm", _fake_llm)
    result = asyncio.run(run_mem_kg_extract({"id": "job_test", "payload": {"atom_id": aid}}))
    assert result.get("ok")
    assert result.get("nodes", 0) >= 2
    ents = list_atom_entities(aid)
    assert any("支付" in str(e.get("node_name") or "") for e in ents)
    st = kg.stats(mem_kb_id(ns))
    assert st["nodeCount"] >= 2
    assert st["edgeCount"] >= 1


def test_apply_extracted_graph_no_heuristic_fill(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Empty LLM graph must not invent edges."""
    from evoflow.knowledge.owned import kg
    from evoflow.memory.facade import remember
    from evoflow.memory.kg_extract import apply_extracted_graph, mem_kb_id
    from evoflow.memory.namespaces import agent_ns
    from evoflow.memory.store import get_atom

    monkeypatch.setattr("evoflow.memory.facade._schedule_kg_batch", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_threshold", lambda *_a, **_k: None)
    ns = agent_ns("main")
    aid = remember(ns, "支付 API", layer="semantic", confidence=0.9, source="manual")
    atom = get_atom(aid)
    applied = apply_extracted_graph(atom, {"nodes": [], "edges": []})
    assert applied["nodes"] == 0
    assert applied["edges"] == 0
    st = kg.stats(mem_kb_id(ns))
    assert st["nodeCount"] == 0


def test_mem_kg_extract_fails_without_llm_fallback(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.memory.facade import remember
    from evoflow.memory.kg_extract import run_mem_kg_extract
    from evoflow.memory.namespaces import agent_ns

    ns = agent_ns("main")
    monkeypatch.setattr("evoflow.memory.facade._schedule_kg_batch", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_threshold", lambda *_a, **_k: None)
    aid = remember(ns, "支付 API 重构", layer="episodic", confidence=0.9, source="manual")

    async def _boom(_atom):
        raise ValueError("LLM down")

    monkeypatch.setattr("evoflow.memory.kg_extract.extract_graph_llm", _boom)
    with pytest.raises(ValueError, match="LLM down"):
        asyncio.run(run_mem_kg_extract({"id": "job_x", "payload": {"atom_id": aid}}))


def test_remember_marks_dirty_not_per_atom_job(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.knowledge.owned import jobs
    from evoflow.memory.facade import remember
    from evoflow.memory.kg_extract import dirty_count, mem_kb_id
    from evoflow.memory.namespaces import agent_ns

    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_threshold", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "evoflow.knowledge.owned.worker.ensure_owned_kb_worker_started",
        lambda: None,
    )
    ns = agent_ns("kgbatch")
    a1 = remember(ns, "支付 API 重构完成", layer="episodic", kind="episode", confidence=0.9, source="manual")
    a2 = remember(ns, "webhook 校验已拆分", layer="episodic", kind="episode", confidence=0.9, source="manual")
    assert a1 and a2
    assert dirty_count(ns) >= 2
    kb = mem_kb_id(ns)
    listed = jobs.list_jobs(kb, limit=50)
    batch_jobs = [j for j in listed if j.get("type") == "mem_kg_batch"]
    extract_jobs = [j for j in listed if j.get("type") == "mem_kg_extract"]
    assert len(batch_jobs) == 1
    assert extract_jobs == []


def test_mem_kg_batch_one_llm_many_atoms(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.knowledge.owned import kg
    from evoflow.memory.facade import remember
    from evoflow.memory.kg_extract import (
        dirty_count,
        list_atom_entities,
        mark_atoms_kg_dirty,
        mem_kb_id,
        run_mem_kg_batch,
    )
    from evoflow.memory.namespaces import agent_ns

    monkeypatch.setattr("evoflow.memory.facade._schedule_kg_batch", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_threshold", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.kg_extract.enqueue_mem_kg_batch", lambda *_a, **_k: None)

    ns = agent_ns("kgbatch2")
    a1 = remember(ns, "完成了支付 API", layer="episodic", kind="episode", confidence=0.9, source="manual")
    a2 = remember(ns, "启用 webhook 校验", layer="episodic", kind="episode", confidence=0.9, source="manual")
    mark_atoms_kg_dirty(ns, [a1, a2])

    calls = {"n": 0}

    async def _fake_batch(atoms):
        calls["n"] += 1
        return {
            str(atoms[0]["id"]): {
                "nodes": [{"name": "支付 API", "kind": "concept"}],
                "edges": [],
            },
            str(atoms[1]["id"]): {
                "nodes": [{"name": "webhook", "kind": "concept"}],
                "edges": [],
            },
        }

    monkeypatch.setattr("evoflow.memory.kg_extract.extract_graph_llm_batch", _fake_batch)
    result = asyncio.run(run_mem_kg_batch({"id": "job_b", "payload": {"namespace": ns}}))
    assert result.get("ok")
    assert result.get("processed") == 2
    assert calls["n"] == 1
    assert dirty_count(ns) == 0
    assert list_atom_entities(a1)
    assert list_atom_entities(a2)
    st = kg.stats(mem_kb_id(ns))
    assert st["nodeCount"] >= 2


def test_batch_skips_section_and_bootstrap(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.memory.facade import remember
    from evoflow.memory.kg_extract import mark_atoms_kg_dirty, run_mem_kg_batch
    from evoflow.memory.namespaces import agent_ns

    monkeypatch.setattr("evoflow.memory.facade._schedule_kg_batch", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_threshold", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.kg_extract.enqueue_mem_kg_batch", lambda *_a, **_k: None)

    ns = agent_ns("kgskip")
    sec = remember(
        ns,
        "用户在做 EvoFlow",
        layer="semantic",
        kind="section:user.workContext",
        subject_key="section.user.workContext",
        confidence=0.9,
        source="updater",
    )
    boot = remember(
        ns,
        "顶层模块 ocr/",
        layer="semantic",
        kind="module",
        confidence=0.9,
        source="bootstrap",
    )
    mark_atoms_kg_dirty(ns, [sec, boot])

    async def _should_not_run(_atoms):
        raise AssertionError("LLM should not run for skipped atoms")

    monkeypatch.setattr("evoflow.memory.kg_extract.extract_graph_llm_batch", _should_not_run)
    result = asyncio.run(run_mem_kg_batch({"id": "job_s", "payload": {"namespace": ns}}))
    assert result.get("ok")
    assert result.get("processed") == 0
    assert result.get("skipped") == 2

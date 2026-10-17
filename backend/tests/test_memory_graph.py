"""Tests for memory graph expand + payload."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def owned_memory_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOFLOW_KNOWLEDGE_ROOT", str(root))
    monkeypatch.setenv("EVOFLOW_HOME", str(tmp_path))
    from evoflow.agents.memory.storage import reset_storage_for_tests
    from evoflow.config.memory_config import MemoryConfig, set_memory_config
    from evoflow.knowledge.owned.db import reset_db_state_for_tests

    reset_db_state_for_tests()
    reset_storage_for_tests()
    set_memory_config(MemoryConfig())
    yield root
    set_memory_config(MemoryConfig())
    reset_db_state_for_tests()
    reset_storage_for_tests()


def test_graph_expand_hops_default_zero(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.config.memory_config import MemoryConfig, set_memory_config
    from evoflow.memory.facade import recall, remember
    from evoflow.memory.kg_extract import apply_extracted_graph
    from evoflow.memory.namespaces import agent_ns
    from evoflow.memory.store import get_atom

    set_memory_config(MemoryConfig())
    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_kg_extract", lambda *_a, **_k: None)
    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_threshold", lambda *_a, **_k: None)

    ns = agent_ns("main")
    a1 = remember(ns, "支付 API 重构完成", layer="episodic", confidence=0.9, source="manual")
    a2 = remember(ns, "webhook 校验拆分方案", layer="semantic", confidence=0.9, source="manual")
    apply_extracted_graph(
        get_atom(a1),
        {
            "nodes": [{"name": "支付 API"}, {"name": "webhook 校验"}],
            "edges": [{"src": "支付 API", "rel": "RELATED", "dst": "webhook 校验"}],
        },
    )
    apply_extracted_graph(
        get_atom(a2),
        {
            "nodes": [{"name": "webhook 校验"}],
            "edges": [],
        },
    )

    # hops=0: only keyword/hybrid, should not pull neighbor solely via graph
    hits0 = recall([ns], "支付 API", top_k=8, max_chars=4000)
    ids0 = {h["id"] for h in hits0}

    from evoflow.config.memory_config import MemoryConfig, MemoryGraphConfig, set_memory_config

    set_memory_config(MemoryConfig(graph=MemoryGraphConfig(expand_hops=1, extract_enabled=False)))
    hits1 = recall([ns], "支付 API", top_k=8, max_chars=4000)
    ids1 = {h["id"] for h in hits1}
    assert a1 in ids0 or a1 in ids1
    # With expand=1, neighbor atom about webhook should be reachable
    assert a2 in ids1


def test_get_graph_and_atoms_for_node(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.memory.facade import remember
    from evoflow.memory.graph import atoms_for_node, get_graph
    from evoflow.memory.kg_extract import apply_extracted_graph, mem_kb_id
    from evoflow.memory.namespaces import agent_ns
    from evoflow.memory.store import get_atom

    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_kg_extract", lambda *_a, **_k: None)
    ns = agent_ns("main")
    aid = remember(ns, "支付 API", layer="episodic", confidence=0.9, source="manual")
    apply_extracted_graph(
        get_atom(aid),
        {"nodes": [{"name": "支付 API"}], "edges": []},
    )
    g = get_graph(ns)
    assert g["kbId"] == mem_kb_id(ns)
    assert g["nodeCount"] >= 1
    assert g.get("expand_hops_default") == 0
    node_id = g["nodes"][0]["id"]
    linked = atoms_for_node(node_id)
    assert any(a["id"] == aid for a in linked)


def test_deleted_atom_not_in_node_atoms(owned_memory_root: Path, monkeypatch: pytest.MonkeyPatch):
    from evoflow.memory.facade import forget, remember
    from evoflow.memory.graph import atoms_for_node, get_graph
    from evoflow.memory.kg_extract import apply_extracted_graph
    from evoflow.memory.namespaces import agent_ns
    from evoflow.memory.store import get_atom

    monkeypatch.setattr("evoflow.memory.facade._maybe_enqueue_kg_extract", lambda *_a, **_k: None)
    ns = agent_ns("main")
    aid = remember(ns, "临时实体记忆", layer="semantic", confidence=0.9, source="manual")
    apply_extracted_graph(get_atom(aid), {"nodes": [{"name": "临时实体"}], "edges": []})
    g = get_graph(ns)
    node_id = g["nodes"][0]["id"]
    assert atoms_for_node(node_id)
    forget(aid)
    assert atoms_for_node(node_id) == []

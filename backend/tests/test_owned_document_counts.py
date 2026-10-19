"""``documentCount`` must count documents in the KB's own index DB.

Regression: ``_document_counts_by_kb`` treated an empty ``storage_dir`` as
"not migrated yet" and counted rows in the central ``kb_documents`` table —
empty after the per-KB split. The builtin user guide (created without a
``storage_dir``) therefore reported ``documentCount: 0`` while its documents
live in the default per-KB location, and the UI status dot went grey
("upload your first document") next to a fully indexed knowledge base.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def owned_counts_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOFLOW_KNOWLEDGE_ROOT", str(root))
    monkeypatch.setenv("EVOFLOW_HOME", str(tmp_path))
    from evoflow.knowledge.owned.db import reset_db_state_for_tests

    reset_db_state_for_tests()
    yield root
    reset_db_state_for_tests()


def _register_kb(kb_id: str, storage_dir: str = "") -> None:
    from evoflow.knowledge.owned.ids import utc_now
    from evoflow.knowledge.owned.db import db

    now = utc_now()
    with db() as conn:
        conn.execute(
            "INSERT INTO kb_bases (id, name, storage_dir, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (kb_id, kb_id, storage_dir, now, now),
        )


def _kb_row(kb_id: str):
    from evoflow.knowledge.owned.db import db

    with db() as conn:
        return conn.execute(
            "SELECT id, storage_dir FROM kb_bases WHERE id=?", (kb_id,)
        ).fetchall()


def _add_doc(kb_id: str, doc_id: str) -> None:
    from evoflow.knowledge.owned.ids import utc_now
    from evoflow.knowledge.owned.kb_conn import db_for_kb

    now = utc_now()
    with db_for_kb(kb_id) as conn:
        conn.execute(
            "INSERT INTO kb_documents (id, kb_id, parse_status, created_at, updated_at)"
            " VALUES (?, ?, 'completed', ?, ?)",
            (doc_id, kb_id, now, now),
        )


def test_counts_per_kb_db_when_storage_dir_empty(owned_counts_root: Path):
    from evoflow.knowledge.owned import service

    _register_kb("kb_count_test")
    _add_doc("kb_count_test", "doc_count_1")
    _add_doc("kb_count_test", "doc_count_2")

    counts = service._document_counts_by_kb(_kb_row("kb_count_test"))

    assert counts.get("kb_count_test") == 2, (
        "documents in the default per-KB location must be counted"
    )


def test_counts_explicit_storage_dir_still_works(owned_counts_root: Path, tmp_path: Path):
    from evoflow.knowledge.owned import service

    storage = tmp_path / "custom-kb"
    _register_kb("kb_count_explicit", str(storage))
    _add_doc("kb_count_explicit", "doc_count_x")

    counts = service._document_counts_by_kb(_kb_row("kb_count_explicit"))

    assert counts.get("kb_count_explicit") == 1

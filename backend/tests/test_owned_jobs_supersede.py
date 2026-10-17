"""Stale terminal-error job rows must be superseded by a later successful run.

Regression: a parse_index job that burned its retries left a permanent
``state='error'`` row in ``kb_jobs``; even after the document was re-parsed
successfully (new ``done`` job), ``job_stats`` kept returning the stale error
row and the UI index-status banner showed a failure forever.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def owned_jobs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOFLOW_KNOWLEDGE_ROOT", str(root))
    monkeypatch.setenv("EVOFLOW_HOME", str(tmp_path))
    from evoflow.knowledge.owned.db import reset_db_state_for_tests

    reset_db_state_for_tests()
    yield root
    reset_db_state_for_tests()


def _job_state(job_id: str) -> tuple[str, str]:
    from evoflow.knowledge.owned.db import db

    with db() as conn:
        row = conn.execute(
            "SELECT state, error_message FROM kb_jobs WHERE id=?", (job_id,)
        ).fetchone()
        assert row is not None, f"job {job_id} missing"
        return str(row["state"]), str(row["error_message"] or "")


def test_success_supersedes_older_error_jobs(owned_jobs_root: Path):
    from evoflow.knowledge.owned import jobs

    kb, doc = "kb_supersede_test", "doc_supersede_test"

    failed = jobs.enqueue(kb_id=kb, doc_id=doc, type="parse_index")
    jobs.complete(failed["id"], error="download failed", permanent=True)
    assert _job_state(failed["id"])[0] == "error"

    retried = jobs.enqueue(kb_id=kb, doc_id=doc, type="parse_index")
    jobs.complete(retried["id"])

    state, message = _job_state(failed["id"])
    assert state != "error", "stale error row still shown to the UI banner"
    assert "superseded" in message.lower()

    state, _ = _job_state(retried["id"])
    assert state == "done"


def test_newer_error_after_success_is_kept(owned_jobs_root: Path):
    from evoflow.knowledge.owned import jobs

    kb, doc = "kb_supersede_test", "doc_supersede_test2"

    ok = jobs.enqueue(kb_id=kb, doc_id=doc, type="parse_index")
    jobs.complete(ok["id"])

    later_failed = jobs.enqueue(kb_id=kb, doc_id=doc, type="parse_index")
    jobs.complete(later_failed["id"], error="broken again", permanent=True)

    state, message = _job_state(later_failed["id"])
    assert state == "error", "a failure newer than the last success must stay visible"
    assert "broken again" in message


def test_other_job_types_are_not_superseded(owned_jobs_root: Path):
    from evoflow.knowledge.owned import jobs

    kb, doc = "kb_supersede_test", "doc_supersede_test3"

    failed = jobs.enqueue(kb_id=kb, doc_id=doc, type="summary_doc")
    jobs.complete(failed["id"], error="summary failed", permanent=True)

    ok = jobs.enqueue(kb_id=kb, doc_id=doc, type="parse_index")
    jobs.complete(ok["id"])

    state, _ = _job_state(failed["id"])
    assert state == "error", "a different job type's error must not be superseded"

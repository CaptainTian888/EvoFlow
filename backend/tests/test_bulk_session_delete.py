"""Bulk session delete — semantic parity + perf shape for role deletion.

The user-reported symptom: deleting an agent (with a linked employee role)
took tens of seconds and froze every other panel afterward. Root cause was
``ProactiveRepository.delete_role`` wiping each session via
``delete_session_full`` — per session it re-ran the full ``load_session_map()``
table scan (7k+ rows) and issued one self-loop HTTP DELETE to LangGraph, all
on the event loop thread.

The fix adds ``delete_sessions_bulk``: one transaction for all session tables,
threadIds read via indexed single-row queries, one bulk LG prune call.
These tests lock in the semantic parity (tombstone, messages, business tables)
and that the LG prune is issued exactly once.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(_BACKEND_ROOT / "packages" / "harness"))


def _ensure_subagent_mock() -> None:
    if "evoflow.subagents.executor" not in sys.modules:
        executor_mock = MagicMock()
        executor_mock.SubagentExecutor = MagicMock
        executor_mock.SubagentResult = MagicMock
        executor_mock.SubagentStatus = MagicMock
        executor_mock.MAX_CONCURRENT_SUBAGENTS = 5
        executor_mock.get_background_task_result = MagicMock()
        sys.modules["evoflow.subagents.executor"] = executor_mock


_ensure_subagent_mock()


class _BulkDeleteTestBase(unittest.TestCase):
    tmp_dir: tempfile.TemporaryDirectory | None = None
    db_path: str | None = None
    _previous_storage_env: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_dir = tempfile.TemporaryDirectory(prefix="evoflow-bulkdel-test-")
        cls.db_path = str(Path(cls.tmp_dir.name) / "evoflow.db")
        cls._previous_storage_env = os.environ.get("EVOFLOW_STORAGE_SQLITE_PATH")
        os.environ["EVOFLOW_STORAGE_SQLITE_PATH"] = cls.db_path

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._previous_storage_env is None:
            os.environ.pop("EVOFLOW_STORAGE_SQLITE_PATH", None)
        else:
            os.environ["EVOFLOW_STORAGE_SQLITE_PATH"] = cls._previous_storage_env
        if cls.tmp_dir is not None:
            cls.tmp_dir.cleanup()
            cls.tmp_dir = None

    def setUp(self) -> None:
        from evoflow.persistence import db as db_mod
        from evoflow.persistence.schema import ensure_app_schema
        from evoflow.persistence.session_repositories import invalidate_session_select_cache

        db_mod.reset_db_for_tests()
        conn = db_mod.get_db(storage_sqlite_path=self.db_path)
        ensure_app_schema(conn)
        invalidate_session_select_cache()

    def tearDown(self) -> None:
        from evoflow.persistence import db as db_mod
        from evoflow.persistence.session_repositories import invalidate_session_select_cache

        invalidate_session_select_cache()
        db_mod.reset_db_for_tests()

    @staticmethod
    def _seed_session(session_key: str, *, thread_id: str | None = None) -> None:
        from evoflow.persistence import chat_message_repositories as msg_repo
        from evoflow.persistence.session_repositories import upsert_session_row

        upsert_session_row(session_key, title="t", context={})
        if thread_id:
            upsert_session_row(session_key, thread_id=thread_id, title="t", context={})
        msg_repo.append_message(
            session_key,
            role="user",
            content="hello",
        )


class DeleteSessionsBulkTest(_BulkDeleteTestBase):
    def test_tombstones_sessions_and_clears_messages(self) -> None:
        from evoflow.persistence import chat_message_repositories as msg_repo
        from evoflow.persistence import session_repositories as sess_repo
        from evoflow.persistence.chat_session_service import delete_sessions_bulk
        from evoflow.persistence.db import get_db

        sk = "proactive:tester:chat:1"
        self._seed_session(sk, thread_id=None)
        self.assertGreater(msg_repo.get_message_count(sk), 0) if hasattr(
            msg_repo, "get_message_count"
        ) else None

        out = asyncio.run(delete_sessions_bulk([sk]))
        self.assertTrue(out["ok"])
        self.assertEqual(out["deleted"], 1)

        conn = get_db()
        row = conn.execute(
            "SELECT is_deleted FROM evoflow_chat_sessions WHERE session_key = ?", (sk,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(int(row[0]), 1)
        left = conn.execute(
            "SELECT COUNT(*) FROM evoflow_chat_messages WHERE session_key = ?", (sk,)
        ).fetchone()[0]
        self.assertEqual(left, 0)
        # 删除后 is_session_deleted 立即为真
        self.assertTrue(sess_repo.is_session_deleted(sk))

    def test_main_session_key_is_ignored(self) -> None:
        from evoflow.persistence.session_repositories import MAIN_SESSION_KEY
        from evoflow.persistence.chat_session_service import delete_sessions_bulk

        out = asyncio.run(delete_sessions_bulk([MAIN_SESSION_KEY, "", "  "]))
        self.assertTrue(out["ok"])
        self.assertEqual(out["deleted"], 0)

    def test_bulk_prune_called_once_with_all_thread_ids(self) -> None:
        from evoflow.persistence import chat_session_service as svc

        sk1 = "proactive:tester:chat:2"
        sk2 = "proactive:tester:chat:3"
        self._seed_session(sk1, thread_id="11111111-1111-1111-1111-111111111111")
        self._seed_session(sk2, thread_id="22222222-2222-2222-2222-222222222222")

        with patch.object(
            svc, "delete_langgraph_threads_bulk", return_value=2
        ) as prune_mock:
            out = asyncio.run(svc.delete_sessions_bulk([sk1, sk2]))
        self.assertEqual(prune_mock.call_count, 1)
        got = prune_mock.call_args[0][0]
        self.assertEqual(sorted(got), sorted([
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]))
        self.assertEqual(out["threads"], 2)
        self.assertEqual(out["langgraph_pruned"], 2)

    def test_transaction_wipe_covers_business_tables(self) -> None:
        from evoflow.persistence.chat_session_service import delete_sessions_bulk
        from evoflow.persistence.db import get_db

        sk = "proactive:tester:chat:4"
        self._seed_session(sk)
        conn = get_db()
        conn.execute(
            "INSERT INTO evoflow_todos (session_key, thread_id, todos_json, updated_at) VALUES (?, '', '[]', '2026-01-01')",
            (sk,),
        )
        conn.execute(
            "INSERT INTO evoflow_artifacts (session_key, thread_id, artifact_id, path, name, updated_at) VALUES (?, '', 'a1', 'p', 'a.txt', '2026-01-01')",
            (sk,),
        )
        conn.commit()

        asyncio.run(delete_sessions_bulk([sk]))
        todos = conn.execute(
            "SELECT COUNT(*) FROM evoflow_todos WHERE session_key = ?", (sk,)
        ).fetchone()[0]
        arts = conn.execute(
            "SELECT COUNT(*) FROM evoflow_artifacts WHERE session_key = ?", (sk,)
        ).fetchone()[0]
        self.assertEqual(todos, 0)
        self.assertEqual(arts, 0)


class BulkLangGraphPruneTest(unittest.TestCase):
    def test_prune_endpoint_payload_shape(self) -> None:
        """批量接口应发一次 POST /threads/prune，带 thread_ids + strategy。"""
        from evoflow.persistence import chat_session_service as svc

        calls: list[tuple[str, str, dict | None]] = []

        class _Resp:
            status_code = 200

            def json(self) -> dict:
                return {"pruned_count": 2}

        async def _fake_request(method, path, *, json_body=None, params=None):
            calls.append((method, path, json_body))
            return _Resp()

        with patch.object(svc, "_langgraph_request", side_effect=_fake_request):
            out = asyncio.run(
                svc.delete_langgraph_threads_bulk([
                    "11111111-1111-1111-1111-111111111111",
                    "22222222-2222-2222-2222-222222222222",
                ])
            )
        self.assertEqual(out, 2)
        self.assertEqual(len(calls), 1)
        method, path, body = calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "threads/prune")
        self.assertEqual(body["strategy"], "delete")
        self.assertEqual(len(body["thread_ids"]), 2)

    def test_prune_failure_falls_back_per_thread(self) -> None:
        from evoflow.persistence import chat_session_service as svc

        class _Resp:
            status_code = 500

        per_thread_calls: list[str] = []

        async def _bulk_fail(method, path, *, json_body=None, params=None):
            return _Resp()

        class _DelResp:
            status_code = 204

        async def _del(thread_id):
            per_thread_calls.append(thread_id)
            return True

        tids = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
        with patch.object(svc, "_langgraph_request", side_effect=_bulk_fail):
            with patch.object(
                svc, "delete_langgraph_thread", side_effect=_del
            ) as del_mock:
                out = asyncio.run(svc.delete_langgraph_threads_bulk(tids))
        self.assertEqual(out, 2)
        self.assertEqual(del_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()

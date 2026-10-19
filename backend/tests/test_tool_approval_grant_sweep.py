"""Regression tests for tool approval grant sweep (「始终允许本项目」).

User-reported symptom: after picking 「始终允许本项目」 on the first gated
tool of a batch, the sibling tools below still asked for approval one by one.
Root cause: siblings in the same model turn are registered pending BEFORE the
user clicks (``_register_sibling_pending_approvals``), and the approve path
persisted the session-level tool_name grant without applying it to those
already-registered pending rows — so「本会话内同类操作不再询问」never held
for the rest of the batch.

The approve path must sweep remaining pending rows already covered by the
persisted grants (same tool_name / exact signature) and approve them too.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


class ToolApprovalGrantSweepTest(unittest.TestCase):
    """Per-test isolated ``evoflow.db`` in a temp file with full schema."""

    tmp_dir: tempfile.TemporaryDirectory | None = None
    db_path: str | None = None
    _previous_storage_env: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_dir = tempfile.TemporaryDirectory(prefix="evoflow-approval-sweep-")
        cls.db_path = str(Path(cls.tmp_dir.name) / "evoflow.db")
        cls._previous_storage_env = os.environ.get("EVOFLOW_DB_PATH")
        os.environ["EVOFLOW_DB_PATH"] = cls.db_path

    @classmethod
    def tearDownClass(cls) -> None:
        # 先关共享连接，否则 Windows 下临时目录清理会因文件被占用而失败
        try:
            from evoflow.persistence import db as db_mod

            db_mod.reset_db_for_tests()
        except Exception:
            pass
        if cls._previous_storage_env is None:
            os.environ.pop("EVOFLOW_DB_PATH", None)
        else:
            os.environ["EVOFLOW_DB_PATH"] = cls._previous_storage_env
        if cls.tmp_dir is not None:
            cls.tmp_dir.cleanup()
            cls.tmp_dir = None

    def setUp(self) -> None:
        from evoflow.persistence import db as db_mod
        from evoflow.persistence.schema import ensure_app_schema

        db_mod.reset_db_for_tests()
        conn = db_mod.get_db(storage_sqlite_path=self.db_path)
        ensure_app_schema(conn)
        import evoflow.agents.tool_approval_service as tas

        self._tas = tas
        # reset_db_for_tests 只关连接不清数据；类级 DB 文件跨用例共享，
        # 会话级授权（tool_names）会从上一个用例泄漏 → 每个用例独立 sk。
        self._sk = f"sk_sweep_{id(self)}"
        self._prev_session_for_thread = tas._session_for_thread
        tas._session_for_thread = lambda tid: (self._sk, "tid_sweep")

    def tearDown(self) -> None:
        self._tas._session_for_thread = self._prev_session_for_thread

    def _register(self, tc_id: str, command: str) -> None:
        from evoflow.agents.tool_approval_service import append_pending, make_pending_entry

        append_pending(
            "tid_sweep",
            make_pending_entry(
                tool_call_id=tc_id,
                tool_name="terminal",
                args={"command": command},
                summary=command,
            ),
        )

    def test_approve_remember_sweeps_granted_siblings(self) -> None:
        tas = self._tas
        self._register("tc_1", "echo one")
        self._register("tc_2", "echo two")

        result = tas.apply_user_approval(
            "tid_sweep",
            {"action": "approve_remember", "tool_call_id": "tc_1"},
        )
        from evoflow.persistence import tool_approval_repositories as ta_repo

        self.assertEqual(
            str(ta_repo.get_approval_row(self._sk, "tc_1")["status"]),
            ta_repo.STATUS_APPROVED,
        )
        # 兄弟 tc_2 同名工具已被「始终允许本项目」覆盖 → 一并批准
        self.assertEqual(
            str(ta_repo.get_approval_row(self._sk, "tc_2")["status"]),
            ta_repo.STATUS_APPROVED,
        )
        grants = ta_repo.load_runtime_signatures(self._sk)
        self.assertIn("terminal", grants.get("tool_names") or [])
        self.assertEqual(sorted(result.replay_tool_call_ids), ["tc_1", "tc_2"])

    def test_plain_approve_does_not_sweep_uncovered_sibling(self) -> None:
        tas = self._tas
        self._register("tc_1", "echo one")
        self._register("tc_2", "echo two")

        tas.apply_user_approval("tid_sweep", {"action": "approve", "tool_call_id": "tc_1"})

        from evoflow.persistence import tool_approval_repositories as ta_repo

        self.assertEqual(
            str(ta_repo.get_approval_row(self._sk, "tc_1")["status"]),
            ta_repo.STATUS_APPROVED,
        )
        # 仅这一次：不同命令的兄弟未被会话授权覆盖，仍待授权
        self.assertEqual(
            str(ta_repo.get_approval_row(self._sk, "tc_2")["status"]),
            ta_repo.STATUS_PENDING,
        )


if __name__ == "__main__":
    unittest.main()

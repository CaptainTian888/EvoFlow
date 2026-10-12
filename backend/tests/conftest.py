"""Test configuration for the backend test suite.

Sets up sys.path and pre-mocks modules that would cause circular import
issues when unit-testing lightweight config/registry code in isolation.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Make 'app' and 'evoflow' importable from any working directory
_backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(_backend_root))
# evoflow package lives in packages/harness (editable install also exposes it)
sys.path.insert(0, str(_backend_root / "packages" / "harness"))

# Break the circular import chain that exists in production code:
#   evoflow.subagents.__init__
#     -> .executor (SubagentExecutor, SubagentResult)
#       -> evoflow.agents.thread_state
#         -> evoflow.agents.__init__
#           -> lead_agent.agent
#             -> subagent_limit_middleware
#               -> evoflow.subagents.executor  <-- circular!
#
# By injecting a mock for evoflow.subagents.executor *before* any test module
# triggers the import, __init__.py's "from .executor import ..." succeeds
# immediately without running the real executor module.
_executor_mock = MagicMock()
_executor_mock.SubagentExecutor = MagicMock
_executor_mock.SubagentResult = MagicMock
_executor_mock.SubagentStatus = MagicMock
_executor_mock.MAX_CONCURRENT_SUBAGENTS = 5
_executor_mock.get_background_task_result = MagicMock()

sys.modules["evoflow.subagents.executor"] = _executor_mock

# ── 收集隔离：test_v4_bridge_e2e.py（orphaned，待其属主决策） ──────────────
# 该用例 import `app.gateway.v4.langgraph_v4_bridge`，但：
#   - 该模块在本仓库 git 历史中从不存在（git log 无记录）；
#   - 它引用的符号 HubProjectionWriter / feed_agui_events / feed_payloads_to_v4
#     在整个 app/ 下也无任何定义，只出现在该测试文件自身。
# 现存的等价模块是 app/gateway/v4/agui_to_v4_projector.py，但对外 API 不同
# （只有 _TranslatorState / translate_agui_events）。因此无法在不臆造契约的前提下
# 修复该 import——强行让收集通过只会得到一个"绿但无意义"的测试。
# 故先隔离其收集，使整体 collect 能通过；原文件原样保留，待属主确认该用例
# 所测的 v4 桥接契约（是被删了还是改名了）后再决定重写或删除。
collect_ignore = ["test_v4_bridge_e2e.py"]

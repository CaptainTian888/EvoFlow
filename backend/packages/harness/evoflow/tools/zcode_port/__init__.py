"""ZCode search + shell tools, reimplemented for the EvoFlow Python harness.

direct 分支保留 Glob/Grep 工具实现；embedded search 分支隐藏 Glob/Grep，
并通过 Bash find/grep 接管搜索。与 ZCode registerBuiltInTools 同一规则。
"""

from evoflow.tools.zcode_port.bash_tool import bash_tool, embedded_search_enabled
from evoflow.tools.zcode_port.glob_grep import glob_tool, grep_tool
from evoflow.tools.zcode_port.task_tools import task_output_tool, task_stop_tool

def zcode_shell_tools() -> list:
    tools = [bash_tool, task_output_tool, task_stop_tool]
    if not embedded_search_enabled():
        tools.extend([glob_tool, grep_tool])
    return tools


__all__ = ["bash_tool", "glob_tool", "grep_tool", "task_output_tool", "task_stop_tool", "zcode_shell_tools"]

r"""Smoke check: agent built-in file tools (host_direct) — one CRUD pass, no pytest.

Run: cd backend && python scripts/smoke_file_tools.py
Exit 0 = all checks passed; 1 = any failure.
"""

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
for _p in (str(_BACKEND), str(_BACKEND / "packages" / "harness")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from evoflow.tools.host_direct.delete_file import delete_file_hd
from evoflow.tools.host_direct.find_file import find_file_hd
from evoflow.tools.host_direct.list_dir import list_dir_hd
from evoflow.tools.host_direct.read_file import read_file_hd
from evoflow.tools.host_direct.str_replace import str_replace_hd
from evoflow.tools.host_direct.workspace_path_guard import runtime_with_workspace
from evoflow.tools.host_direct.write_file import write_file_hd

_seq = iter(range(1000))


def call(tool, **kwargs):
    """Uniform ToolCall-form invoke; unwrap ToolMessage to plain string."""
    result = tool.invoke(
        {"args": kwargs, "name": tool.name, "type": "tool_call", "id": f"smoke-{next(_seq)}"}
    )
    return result.content if hasattr(result, "content") else result


def main() -> int:
    ws = Path(tempfile.mkdtemp(prefix="evoflow-smoke-"))
    rt = runtime_with_workspace(str(ws), thread_id=f"smoke-{uuid.uuid4().hex[:8]}")
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    try:
        # ── 增 create ────────────────────────────────────────────────
        target = ws / "notes" / "hello.txt"
        out = call(write_file_hd, path=str(target), content="hello evo", runtime=rt)
        check("增 write 新建(含父目录)", out.startswith("OK:") and target.exists(), out[:60])

        log = ws / "log.txt"
        call(write_file_hd, path=str(log), content="v1", runtime=rt)
        out = call(write_file_hd, path=str(log), content="v2", append=True, runtime=rt)
        ok = out.startswith("OK: appended") and log.read_text(encoding="utf-8") == "v1\nv2\n"
        check("增 write append 追加", ok, out[:60])

        # ── 查 read ──────────────────────────────────────────────────
        out = call(read_file_hd, path=str(target), runtime=rt)
        check("查 read 全文", out == "hello evo\n", out[:60])

        out = call(read_file_hd, path=str(ws / "ghost.txt"), runtime=rt)
        check("查 read 缺文件报错", out.startswith("Error:") and "File not found" in out, out[:60])

        # ── 改 update ────────────────────────────────────────────────
        out = call(str_replace_hd, path=str(target), old_string="evo", new_string="world", runtime=rt)
        ok = out.startswith("OK: Replaced 1") and target.read_text(encoding="utf-8") == "hello world\n"
        check("改 replace 唯一命中", ok, out[:60])

        out = call(str_replace_hd, path=str(target), old_string="l", new_string="X", runtime=rt)
        ok = out.startswith("Error:") and "appears" in out
        check("改 replace 多命中拒绝", ok, out[:60])

        # ── 删 delete ────────────────────────────────────────────────
        out = call(delete_file_hd, path=str(log), runtime=rt)
        check("删 delete 已存在", out.startswith("OK:") and not log.exists(), out[:60])

        out = call(delete_file_hd, path=str(ws / "ghost.txt"), runtime=rt)
        check("删 delete 缺文件报错", out.startswith("Error:"), out[:60])

        # ── 查 find / list_dir（附加浏览面） ─────────────────────────
        out = call(find_file_hd, pattern="*.txt", root=".", runtime=rt)
        check("查 find glob", out.startswith("Found") and "hello.txt" in out, out[:60])

        out = list_dir_hd(str(ws / "notes"), runtime=rt)
        check("查 list_dir", "hello.txt" in out, out[:60])

    finally:
        shutil.rmtree(ws, ignore_errors=True)

    print()
    print("=" * 62)
    print("冒烟结果 (host_direct file tools CRUD)")
    print("=" * 62)
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}] {name}" + ("" if ok else f"  ->  {detail}"))
    total = len(results)
    print("-" * 62)
    print(f"  {total - failed}/{total} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

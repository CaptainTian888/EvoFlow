"""Bash tool — ZCode shell execution with embedded-search prelude and background tasks.

Source: ZCode packages/contracts/src/tools/bash.ts
        ZCode packages/core/src/tool/handlers/bash.ts (execution surface used by EvoFlow)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langgraph.types import Command

from evoflow.agents.image_staging import command_with_staged_images, stage_image_entry
from evoflow.tools.zcode_port.background import BackgroundBashTask, mark, new_task_id, register_task
from evoflow.tools.zcode_port.capability import resolve_embedded_search_branch_capability
from evoflow.tools.zcode_port.prelude import BASH_DESCRIPTION, BASH_DESCRIPTION_DIRECT, build_embedded_search_prelude

MAX_BASH_TIMEOUT_MS = 600_000
DEFAULT_TIMEOUT_MS = 120_000
MAX_INLINE_CHARS = 20_000

_TRUE = {"true", "1", "yes", "y", "on"}
_FALSE = {"false", "0", "no", "n", "off"}

# ZCode: working directory persists between Bash calls (per thread).
_PERSISTED_CWD: dict[str, str] = {}
_PERSISTED_CWD_LOCK = threading.Lock()
_PWD_MARKER = "__EVOFLOW_PWD__="


def _semantic_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE:
            return True
        if normalized in _FALSE:
            return False
    return default


def _semantic_timeout(value: object) -> int:
    if value is None or value == "":
        return DEFAULT_TIMEOUT_MS
    try:
        parsed = int(float(str(value).strip()))
    except ValueError:
        return DEFAULT_TIMEOUT_MS
    return max(1, min(parsed, MAX_BASH_TIMEOUT_MS))


def bash_shell() -> list[str] | None:
    """Prefer a real POSIX bash so the embedded-search function prelude can run.

    The WindowsApps ``bash.exe`` stub is not a shell; Git's ``bin/bash.exe`` is.
    """
    candidates: list[Path] = []
    found = shutil.which("bash")
    if found and "WindowsApps" not in found.replace("/", "\\"):
        candidates.append(Path(found))
    git = shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        candidates.append(git_path.parent.parent / "bin" / "bash.exe")
        candidates.append(git_path.parent / "bash.exe")
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(env_key)
        if not root:
            continue
        base = Path(root) / ("Programs" if env_key == "LOCALAPPDATA" else "")
        candidates.append(base / "Git" / "bin" / "bash.exe")
    for path in candidates:
        if path.is_file():
            return [str(path)]
    return None


def embedded_search_enabled() -> bool:
    return resolve_embedded_search_branch_capability(bash_available=bash_shell() is not None)


def _workspace_root(runtime: ToolRuntime | None) -> str:
    from evoflow.tools.host_direct.workspace_path_guard import resolve_search_workspace_root

    resolved = resolve_search_workspace_root(runtime=runtime)
    if isinstance(resolved, tuple):
        return resolved[0]
    return os.getcwd()


def _cwd(runtime: ToolRuntime | None) -> str:
    tid = _thread_id(runtime)
    if tid:
        with _PERSISTED_CWD_LOCK:
            persisted = _PERSISTED_CWD.get(tid)
        if persisted and Path(persisted).is_dir():
            return persisted
    return _workspace_root(runtime)


def _remember_cwd(thread_id: str, cwd: str) -> None:
    tid = str(thread_id or "").strip()
    path = str(cwd or "").strip()
    if not tid or not path or not Path(path).is_dir():
        return
    with _PERSISTED_CWD_LOCK:
        _PERSISTED_CWD[tid] = path


def _no_window() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _to_posix(path: str) -> str:
    from evoflow.utils.bundled_tools import to_bash_posix_path

    return to_bash_posix_path(path)


def _embedded_runtime_exports() -> tuple[str, str, str, str, bool]:
    """Return (path_exports, find_cmd, grep_cmd, rg_cmd, wrap_find)."""
    try:
        from evoflow.utils.bundled_tools import (
            bundled_bfs_binary,
            bundled_ripgrep_binary,
            bundled_ugrep_binary,
        )
    except Exception:
        return "", "bfs", "ugrep", "rg", sys.platform != "win32"

    path_dirs: list[str] = []
    find_cmd = "bfs"
    grep_cmd = "ugrep"
    rg_cmd = "rg"
    bfs = bundled_bfs_binary()
    ugrep = bundled_ugrep_binary()
    rg = bundled_ripgrep_binary()
    if bfs:
        find_cmd = _to_posix(bfs)
        path_dirs.append(find_cmd.rsplit("/", 1)[0])
    if ugrep:
        grep_cmd = _to_posix(ugrep)
        path_dirs.append(grep_cmd.rsplit("/", 1)[0])
    if rg:
        rg_cmd = _to_posix(rg)
        path_dirs.append(rg_cmd.rsplit("/", 1)[0])
    # ZCode: Windows does not wrap find unless bfs is actually present.
    wrap_find = bool(bfs) if sys.platform == "win32" else True
    exports = ""
    if path_dirs:
        uniq = []
        for d in path_dirs:
            if d and d not in uniq:
                uniq.append(d)
        exports = "export PATH=\"" + ":".join(uniq) + ":$PATH\"\n"
    return exports, find_cmd, grep_cmd, rg_cmd, wrap_find


def _wrap_with_cwd_and_pwd(command: str, cwd: str) -> str:
    """cd into persisted cwd, run command, echo cwd for the next call (ZCode persist)."""
    posix_cwd = _to_posix(cwd)
    return (
        f'cd "{posix_cwd}" || exit 1\n'
        f"{command}\n"
        f'_ef_ec=$?\n'
        f'printf "\\n{_PWD_MARKER}%s\\n" "$(pwd)"\n'
        f"exit $_ef_ec\n"
    )


def _strip_pwd_marker(text: str, thread_id: str) -> str:
    if _PWD_MARKER not in text:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        if line.startswith(_PWD_MARKER):
            _remember_cwd(thread_id, line[len(_PWD_MARKER) :])
            continue
        kept.append(line)
    return "\n".join(kept)


# PowerShell cmdlets have no meaning inside Git Bash. Routing them through
# ``bash -lc`` pays a login-shell startup (profile, often several seconds on Windows)
# and then fails to find the cmdlet.
_POWERSHELL_CMDLET_RE = re.compile(
    r"(?i)(?:^|[;&|\n]\s*)(?:"
    r"Select-String|Get-ChildItem|Get-Content|Get-Item|Set-Content|Set-Location|"
    r"Out-File|ForEach-Object|Where-Object|Measure-Object|Test-Path|"
    r"Copy-Item|Move-Item|Remove-Item|New-Item|Invoke-WebRequest|Invoke-RestMethod|"
    r"ConvertFrom-Json|ConvertTo-Json|sls|gci|gc|gi"
    r")\b"
)


def _powershell_executable() -> str:
    found = shutil.which("powershell") or shutil.which("powershell.exe")
    return found or "powershell"


def _powershell_argv(command: str, cwd: str) -> list[str] | None:
    """Run an obvious PowerShell script without Git Bash and without a user profile."""
    if sys.platform != "win32":
        return None
    stripped = command.strip()
    if not stripped or not _POWERSHELL_CMDLET_RE.search(stripped):
        return None
    if re.match(r"(?i)^(powershell|pwsh)(\.exe)?\b", stripped):
        return None
    safe_cwd = cwd.replace("'", "''")
    body = (
        f"Set-Location -LiteralPath '{safe_cwd}'; "
        f"{stripped}; "
        f"Write-Output ('{_PWD_MARKER}' + (Get-Location).Path)"
    )
    return [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", body]


def _bash_args(shell: list[str], script: str) -> list[str]:
    # ``-l`` sources .bash_profile / /etc/profile. On Windows Git Bash that startup
    # is the multi-second delay before the command itself runs. The embedded-search
    # functions are already inlined in ``script``, so a login shell is not required.
    return [*shell, "--noprofile", "--norc", "-c", script]


def _script(command: str, *, cwd: str) -> tuple[list[str], str]:
    ps = _powershell_argv(command, cwd)
    if ps is not None:
        return ps, "powershell"
    shell = bash_shell()
    body = _wrap_with_cwd_and_pwd(command, cwd)
    if shell and embedded_search_enabled():
        exports, find_cmd, grep_cmd, rg_cmd, wrap_find = _embedded_runtime_exports()
        prelude = exports + build_embedded_search_prelude(
            find_command=find_cmd,
            grep_command=grep_cmd,
            rg_command=rg_cmd,
            wrap_find=wrap_find,
        )
        return _bash_args(shell, prelude + body), "bash"
    if shell:
        return _bash_args(shell, body), "bash"
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"Set-Location -LiteralPath '{cwd}'; {command}"], "powershell"
    return ["sh", "-c", body], "sh"


def _emit(kind: str, **kwargs: object) -> None:
    from evoflow.tools.host_direct.terminal_stream import (
        emit_background_work,
        emit_terminal_exit,
        emit_terminal_start,
        emit_terminal_stderr,
        emit_terminal_stdout,
    )

    fn = {
        "start": emit_terminal_start,
        "stdout": emit_terminal_stdout,
        "stderr": emit_terminal_stderr,
        "exit": emit_terminal_exit,
        "background": emit_background_work,
    }[kind]
    try:
        fn(**kwargs)  # type: ignore[arg-type]
    except Exception:
        return


def _thread_id(runtime: ToolRuntime | None) -> str:
    if runtime is None or getattr(runtime, "context", None) is None:
        return ""
    ctx = runtime.context
    return str(ctx.get("thread_id") or "").strip()


def _session_key(runtime: ToolRuntime | None) -> str:
    if runtime is None or getattr(runtime, "context", None) is None:
        return ""
    ctx = runtime.context
    return str(ctx.get("session_key") or "").strip()


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_INLINE_CHARS:
        return text, False
    return text[:MAX_INLINE_CHARS] + "\n…[truncated]", True


def _output_file(task_id: str) -> Path:
    root = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp") / "evoflow-bash-tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{task_id}.output"


def _emit_task_notification(task: BackgroundBashTask) -> None:
    if task.notification_sent or not task.thread_id:
        return
    task.notification_sent = True
    from evoflow.tools.zcode_port.notify_continuation import schedule_bash_task_notification_turn
    from evoflow.tools.zcode_port.task_notification import (
        build_bash_task_summary,
        format_local_bash_task_notification,
        normalize_bash_notification_status,
    )

    status = normalize_bash_notification_status(task.status)
    summary = build_bash_task_summary(
        command=task.command,
        description=task.description,
        exit_code=task.exit_code,
        status=status,
    )
    text = format_local_bash_task_notification(
        task_id=task.task_id,
        status=status,
        summary=summary,
        output_file=str(task.output_path),
        tool_use_id=task.tool_call_id or None,
    )
    schedule_bash_task_notification_turn(
        thread_id=task.thread_id,
        session_key=task.session_key,
        notification_text=text,
        task_id=task.task_id,
    )


def _run_foreground(
    command: str,
    timeout_ms: int,
    cwd: str,
    tool_call_id: str,
    *,
    thread_id: str = "",
) -> str:
    argv, _dialect = _script(command, cwd=cwd)
    invocation = tool_call_id or uuid.uuid4().hex
    # CreateProcess requires a Windows path. Git Bash accepts that cwd and converts it.
    _emit("start", invocation_id=invocation, tool_call_id=tool_call_id, command=command)
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_ms / 1000.0,
            **_no_window(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        _emit("stdout", invocation_id=invocation, tool_call_id=tool_call_id, text=stdout)
        _emit("stderr", invocation_id=invocation, tool_call_id=tool_call_id, text=stderr)
        _emit("exit", invocation_id=invocation, tool_call_id=tool_call_id, exit_code=124, success=False)
        out, _ = _clip(stdout)
        err, _ = _clip(stderr)
        return f"status: timed_out\ninterrupted: true\nstdout:\n{out}\nstderr:\n{err}"
    except OSError as exc:
        _emit("exit", invocation_id=invocation, tool_call_id=tool_call_id, exit_code=127, success=False)
        return f"status: spawn_error\ninterrupted: false\nstderr:\n{exc}"
    stdout = _strip_pwd_marker(proc.stdout or "", thread_id)
    stderr = proc.stderr or ""
    _emit("stdout", invocation_id=invocation, tool_call_id=tool_call_id, text=stdout)
    _emit("stderr", invocation_id=invocation, tool_call_id=tool_call_id, text=stderr)
    _emit("exit", invocation_id=invocation, tool_call_id=tool_call_id, exit_code=proc.returncode, success=proc.returncode == 0)
    out, out_tr = _clip(stdout)
    err, err_tr = _clip(stderr)
    status = "completed" if proc.returncode == 0 else "failed"
    return (
        f"status: {status}\nexitCode: {proc.returncode}\ninterrupted: false\n"
        f"stdoutTruncated: {str(out_tr).lower()}\nstderrTruncated: {str(err_tr).lower()}\n"
        f"stdout:\n{out}\nstderr:\n{err}"
    )


def _run_background(
    command: str,
    cwd: str,
    tool_call_id: str,
    description: str,
    *,
    thread_id: str = "",
    session_key: str = "",
) -> str:
    argv, _dialect = _script(command, cwd=cwd)
    task_id = new_task_id()
    output_path = _output_file(task_id)
    # Prefer LangChain tool_call_id so chat cards and the status panel share one key;
    # fall back to workId when the host did not inject one.
    stream_id = (tool_call_id or "").strip() or task_id
    invocation = stream_id
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_no_window(),
        )
    except OSError as exc:
        return f"status: spawn_error\ninterrupted: false\nstderr:\n{exc}"
    task = BackgroundBashTask(
        task_id=task_id,
        command=command,
        description=description,
        output_path=output_path,
        proc=proc,
        tool_call_id=stream_id,
        thread_id=thread_id,
        session_key=session_key,
    )
    register_task(task)
    started_ms = int(task.started_at * 1000)
    _emit("start", invocation_id=invocation, tool_call_id=stream_id, command=command)
    _emit(
        "background",
        work_id=task_id,
        title=description or command[:80],
        command=command,
        tool_call_id=stream_id,
        status="running",
        started_at_ms=started_ms,
    )

    def _pump() -> None:
        chunks: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith(_PWD_MARKER):
                _strip_pwd_marker(line, thread_id)
                continue
            chunks.append(line)
            _emit("stdout", invocation_id=invocation, tool_call_id=stream_id, text=line)
        code = proc.wait()
        text = _strip_pwd_marker("".join(chunks), thread_id)
        output_path.write_text(text, encoding="utf-8", errors="replace")
        # TaskStop may have already marked cancelled.
        if task.status == "running":
            mark(task, status="completed" if code == 0 else "failed", exit_code=code)
        _emit("exit", invocation_id=invocation, tool_call_id=stream_id, exit_code=code, success=code == 0)
        _emit(
            "background",
            work_id=task_id,
            title=description or command[:80],
            command=command,
            tool_call_id=stream_id,
            status=task.status if task.status != "stopped" else "cancelled",
            started_at_ms=started_ms,
        )
        _emit_task_notification(task)

    threading.Thread(target=_pump, name=f"bash-bg-{task_id}", daemon=True).start()
    return (
        f"status: backgrounded\ninterrupted: false\nbackgroundTaskId: {task_id}\n"
        f"persistedOutputPath: {output_path}\n"
        "Command is running in the background. Prefer Read on persistedOutputPath; "
        "TaskOutput can poll this task_id; TaskStop stops it."
    )


def bash_provider_description() -> str:
    if embedded_search_enabled():
        return BASH_DESCRIPTION
    return BASH_DESCRIPTION_DIRECT


_AGENT_BROWSER_SCREENSHOT_RE = re.compile(
    r"\bagent-browser\b[^;&|]*?\bscreenshot\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)",
    re.IGNORECASE,
)
_SCREENSHOT_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _resolve_screenshot_path(raw: str, cwd: str) -> Path | None:
    path_text = str(raw or "").strip().strip("\"'")
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = Path(cwd) / path
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
    except OSError:
        return None
    return None


def _maybe_stage_agent_browser_screenshot(
    runtime: object, command: str, cwd: str, tool_call_id: str, result: str
) -> str | Command:
    """agent-browser screenshot → 像素自动进下一次模型上下文（对齐 ZCode）。

    命中 ``agent-browser … screenshot <path>`` 且文件真实落盘时，把图 stage 成
    ``viewed_images`` auto 条目（path-only），ViewImageMiddleware 在下一次模型
    调用前按 200KB base64 预算压缩注入。文件不存在 / 模型无视觉 / text 路由时
    不 stage，行为与之前完全一致。
    """
    lowered = command.lower()
    if "agent-browser" not in lowered or "screenshot" not in lowered:
        return result
    for raw in _AGENT_BROWSER_SCREENSHOT_RE.findall(command):
        path = _resolve_screenshot_path(raw, cwd)
        if path is None:
            continue
        staged = stage_image_entry(
            runtime=runtime,
            path=str(path),
            mime_type=_SCREENSHOT_MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png"),
            label="browser screenshot",
        )
        if not staged:
            return result
        result = (
            f"{result}\n\n[agent-browser screenshot saved: {path} — staged for your next "
            f"context; you will see the pixels.]"
        )
        return command_with_staged_images(result, tool_call_id, {staged["path"]: staged})
    return result


@tool("bash", description=BASH_DESCRIPTION, parse_docstring=False)
def bash_tool(
    command: str,
    timeout: int | str | None = None,
    description: str | None = None,
    run_in_background: bool | str | None = None,
    dangerouslyDisableSandbox: bool | str | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
    runtime: ToolRuntime = None,
) -> str | Command:
    """Executes a bash command and returns its output.

    timeout: Optional timeout in milliseconds (max 600000).
    description: Clear, concise description of what this command does in active voice.
    run_in_background: Set to true to run this command in the background.
    dangerouslyDisableSandbox: Set this to true to dangerously override sandbox mode and run commands without sandboxing.
    """
    del dangerouslyDisableSandbox  # EvoFlow host-direct already runs on the host; flag is accepted for schema parity.
    cwd = _cwd(runtime)
    timeout_ms = _semantic_timeout(timeout)
    tid = _thread_id(runtime)
    sk = _session_key(runtime)
    if _semantic_bool(run_in_background):
        return _run_background(
            command,
            cwd,
            tool_call_id,
            description or command[:80],
            thread_id=tid,
            session_key=sk,
        )
    result = _run_foreground(command, timeout_ms, cwd, tool_call_id, thread_id=tid)
    return _maybe_stage_agent_browser_screenshot(runtime, command, cwd, tool_call_id, result)

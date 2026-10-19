"""Cross-platform subprocess helpers (Windows console flash mitigation)."""

from __future__ import annotations

import locale
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

# subprocess.CREATE_NO_WINDOW (Python 3.7+); 0x08000000 on older builds
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

_POWERSHELL_ARGS = ("-NoProfile", "-WindowStyle", "Hidden", "-NonInteractive", "-Command")

# Force UTF-8 on redirected stdout/stderr (Chinese Windows defaults to cp936 for Write-Output/echo).
_POWERSHELL_UTF8_BOOTSTRAP = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [Console]::OutputEncoding; "


def subprocess_text_encoding() -> str:
    """Decode child stdout/stderr.

    On Windows we bootstrap shells to UTF-8 (see ``prepare_shell_command``); override via
    ``EVOFLOW_SUBPROCESS_ENCODING`` when needed.
    """
    override = (os.environ.get("EVOFLOW_SUBPROCESS_ENCODING") or "").strip()
    if override:
        return override
    if os.name == "nt":
        return "utf-8"
    pref = (locale.getpreferredencoding(False) or "").strip()
    return pref or "utf-8"


def subprocess_text_io_kwargs() -> dict[str, Any]:
    """Use with ``text=True`` so ``_readerthread`` never raises ``UnicodeDecodeError``."""
    return {"encoding": subprocess_text_encoding(), "errors": "replace"}


def _shell_basename(shell_executable: str) -> str:
    return os.path.basename(str(shell_executable or "")).lower()


def is_powershell_executable(shell_executable: str) -> bool:
    base = _shell_basename(shell_executable)
    return "powershell" in base or base == "pwsh.exe"


def is_cmd_executable(shell_executable: str) -> bool:
    return _shell_basename(shell_executable) == "cmd.exe"


def prepare_shell_command(command: str, shell_executable: str | None = None) -> str:
    """Prefix Windows shell commands so stdout/stderr are UTF-8 (fixes Chinese mojibake)."""
    cmd = str(command or "").strip()
    if os.name != "nt" or not cmd:
        return cmd
    shell = str(shell_executable or "").strip()
    if is_powershell_executable(shell):
        if "[Console]::OutputEncoding" in cmd:
            return cmd
        return _POWERSHELL_UTF8_BOOTSTRAP + cmd
    if is_cmd_executable(shell):
        if cmd.lower().startswith("chcp "):
            return cmd
        return f"chcp 65001 >nul & {cmd}"
    return cmd


def prepare_shell_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Child-process env tweaks for consistent text IO."""
    out = dict(env if env is not None else os.environ)
    if os.name == "nt":
        out.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        from evoflow.persistence.runtime_env import apply_runtime_env_to_mapping

        apply_runtime_env_to_mapping(out)
    except Exception:
        pass
    try:
        from evoflow.skills.loader import get_skills_root_path

        out.setdefault("EVOFLOW_SKILLS_PATH", str(get_skills_root_path()))
    except Exception:
        pass
    return out


# Media / skill subprocesses need vendor keys; strip only generic LLM provider keys.
_PRESERVED_API_KEY_PREFIXES = (
    "VOLCENGINE_",
    "ARK_",
    "JIMENG_",
    "SEEDANCE_",
    "DASHSCOPE_",
    "KLING_",
    "AGNES_",
    "ALIYUN_",
    "BYTEPLUS_",
)


def sanitize_child_process_env(env: dict[str, str]) -> dict[str, str]:
    """Drop LLM API keys from child env; re-inject persisted media credentials for skills."""
    for key in list(env.keys()):
        low = key.lower()
        if not any(kw in low for kw in ("key", "token", "secret", "password", "credential", "auth")):
            continue
        if "API_KEY" not in key.upper() and "AUTH_TOKEN" not in key.upper():
            continue
        if any(key.upper().startswith(p) for p in _PRESERVED_API_KEY_PREFIXES):
            continue
        if key in ("HERMES_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(key, None)
            continue
        if "API_KEY" in key.upper():
            env.pop(key, None)
    try:
        from evoflow.persistence.runtime_env import apply_runtime_env_to_mapping

        apply_runtime_env_to_mapping(env)
    except Exception:
        pass
    return env


def subprocess_hide_window_kwargs() -> dict[str, Any]:
    """Extra kwargs for ``Popen`` / ``run`` / ``asyncio.create_subprocess_exec`` so child shells do not flash a console on Windows.

    Combines ``CREATE_NO_WINDOW`` with ``STARTUPINFO(SW_HIDE)`` when available.
    Batch files (``.cmd`` / ``.bat``) still often flash unless wrapped via
    :func:`wrap_windows_batch_argv` first.
    """
    if os.name != "nt":
        return {}
    out: dict[str, Any] = {}
    if _CREATE_NO_WINDOW:
        out["creationflags"] = _CREATE_NO_WINDOW
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        out["startupinfo"] = si
    except Exception:
        pass
    return out


def wrap_windows_batch_argv(command: str, args: list[str] | None = None) -> tuple[str, list[str]]:
    """Rewrite ``*.cmd`` / ``*.bat`` launches through ``cmd.exe /d /c`` so CREATE_NO_WINDOW sticks.

    Direct CreateProcess on a batch file still flashes a console on many Windows builds;
    launching via ComSpec with CREATE_NO_WINDOW does not.
    """
    argv_tail = list(args or [])
    cmd = str(command or "").strip()
    if os.name != "nt" or not cmd:
        return cmd, argv_tail
    lowered = cmd.lower()
    if not (lowered.endswith(".cmd") or lowered.endswith(".bat")):
        return cmd, argv_tail
    comspec = os.environ.get("ComSpec") or shutil.which("cmd.exe") or "cmd.exe"
    return comspec, ["/d", "/c", cmd, *argv_tail]


def prefer_windows_gui_safe_executable(command: str) -> str:
    """Prefer ``*.exe`` over ``*.cmd``/``*.bat`` shims when both exist on PATH."""
    cmd = str(command or "").strip()
    if os.name != "nt" or not cmd:
        return cmd
    try:
        resolved = shutil.which(cmd) or cmd
    except OSError:
        return cmd
    path = Path(resolved)
    suffix = path.suffix.lower()
    if suffix in {".cmd", ".bat"}:
        exe_sibling = path.with_suffix(".exe")
        try:
            if exe_sibling.is_file():
                return str(exe_sibling)
        except OSError:
            pass
        try:
            which_exe = shutil.which(f"{path.stem}.exe")
        except OSError:
            which_exe = None
        if which_exe:
            return which_exe
    return resolved if resolved else cmd


def harden_windows_stdio_argv(
    command: str, args: list[str] | None = None
) -> tuple[str, list[str]]:
    """Make a stdio MCP / plugin argv less likely to flash a console on Windows.

    Order: prefer ``.exe`` shims → rewrite ``npm``/``npx`` via node cli.js when
    possible → wrap remaining ``.cmd``/``.bat`` through ``cmd.exe /d /c``.
    """
    argv_tail = list(args or [])
    cmd = str(command or "").strip()
    if os.name != "nt" or not cmd:
        return cmd, argv_tail

    stem = Path(cmd).stem.lower()
    if stem in {"npm", "npx"}:
        node = shutil.which("node") or ""
        if stem == "npm":
            prefix = resolve_npm_argv(node)
            if len(prefix) >= 2:
                return prefix[0], [*prefix[1:], *argv_tail]
        if stem == "npx" and node:
            node_dir = Path(node).resolve().parent
            for candidate in (
                node_dir / "node_modules" / "npm" / "bin" / "npx-cli.js",
                node_dir.parent / "lib" / "node_modules" / "npm" / "bin" / "npx-cli.js",
            ):
                try:
                    if candidate.is_file():
                        return node, [str(candidate), *argv_tail]
                except OSError:
                    continue

    cmd = prefer_windows_gui_safe_executable(cmd)
    return wrap_windows_batch_argv(cmd, argv_tail)


_MCP_STDIO_PATCHED = False


def patch_mcp_stdio_no_console_flash() -> bool:
    """Monkey-patch MCP Windows stdio spawn so console windows do not flash.

    The upstream SDK already tries ``CREATE_NO_WINDOW``, but:
    1. its ``except Exception`` path retries *without* the flag;
    2. resolving ``npx``/``npm`` to ``*.cmd`` still flashes on many Windows builds.

    Idempotent; no-op on non-Windows or when ``mcp`` is not installed.
    """
    global _MCP_STDIO_PATCHED
    if os.name != "nt" or _MCP_STDIO_PATCHED:
        return _MCP_STDIO_PATCHED
    try:
        from mcp.os.win32 import utilities as win_util
    except Exception:
        return False

    if getattr(win_util, "_evoflow_no_console_flash", False):
        _MCP_STDIO_PATCHED = True
        return True

    original_create = win_util.create_windows_process
    original_get_exe = win_util.get_windows_executable_command

    def _get_windows_executable_command(command: str) -> str:
        return prefer_windows_gui_safe_executable(original_get_exe(command))

    async def _create_windows_process(
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        errlog: Any = None,
        cwd: Any = None,
    ) -> Any:
        import sys as _sys

        safe_cmd, safe_args = harden_windows_stdio_argv(command, list(args or []))
        hide = subprocess_hide_window_kwargs()
        creationflags = int(hide.get("creationflags") or 0)
        startupinfo = hide.get("startupinfo")
        stderr = errlog if errlog is not None else _sys.stderr
        job = win_util._create_job_object()
        process: Any = None

        try:
            import anyio

            process = await anyio.open_process(
                [safe_cmd, *safe_args],
                env=env,
                creationflags=creationflags,
                stderr=stderr,
                cwd=cwd,
            )
        except Exception:
            # Always keep CREATE_NO_WINDOW — upstream retries without it and flashes.
            popen_obj = subprocess.Popen(
                [safe_cmd, *safe_args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                env=env,
                cwd=cwd,
                bufsize=0,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            process = win_util.FallbackProcess(popen_obj)

        win_util._maybe_assign_process_to_job(process, job)
        return process

    win_util.get_windows_executable_command = _get_windows_executable_command  # type: ignore[assignment]
    win_util.create_windows_process = _create_windows_process  # type: ignore[assignment]
    win_util._evoflow_no_console_flash = True  # type: ignore[attr-defined]
    # Keep a reference so the originals are not GC'd unexpectedly.
    win_util._evoflow_original_create_windows_process = original_create  # type: ignore[attr-defined]
    win_util._evoflow_original_get_windows_executable_command = original_get_exe  # type: ignore[attr-defined]

    # mcp.client.stdio binds these names at import time — patch both modules.
    try:
        import mcp.client.stdio as mcp_stdio

        mcp_stdio.get_windows_executable_command = _get_windows_executable_command  # type: ignore[attr-defined]
        mcp_stdio.create_windows_process = _create_windows_process  # type: ignore[attr-defined]
    except Exception:
        pass

    _MCP_STDIO_PATCHED = True
    return True


def resolve_npm_argv(node_path: str | None = None) -> list[str]:
    """Argv prefix to run npm without flashing ``cmd.exe`` on Windows when possible.

    Prefer ``node …/npm-cli.js`` over ``npm.cmd`` (batch files often show a console).
    Falls back to ``npm.exe`` / ``npm.cmd`` / ``npm``; callers must pass
    ``subprocess_hide_window_kwargs()`` to hide the console on Windows.
    """
    node = str(node_path or "").strip()
    if not node:
        node = shutil.which("node") or ""
    if node:
        node_dir = Path(node).resolve().parent
        for candidate in (
            node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js",
            node_dir.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js",
        ):
            try:
                if candidate.is_file():
                    return [node, str(candidate)]
            except OSError:
                continue
    if os.name == "nt":
        npm = shutil.which("npm.exe") or shutil.which("npm.cmd") or shutil.which("npm") or ""
    else:
        npm = shutil.which("npm") or ""
    return [npm] if npm else []


def detect_shell() -> tuple[str, list[str], bool]:
    """Pick host shell. Returns ``(executable, prefix_args, use_shell_bool)``."""
    if os.name == "nt":
        for candidate in ("pwsh.exe", "powershell.exe", "cmd.exe"):
            full = shutil.which(candidate)
            if full:
                if "powershell" in candidate.lower():
                    return full, list(_POWERSHELL_ARGS), False
                if candidate == "cmd.exe":
                    return full, ["/c"], False
        raise RuntimeError("No shell found on Windows")
    for candidate in ("/bin/bash", "/bin/zsh", "/bin/sh"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate, [], True
    raise RuntimeError("No shell found")

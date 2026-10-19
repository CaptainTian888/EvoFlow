"""Windows console-flash mitigations for subprocess / MCP stdio."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from evoflow.utils.subprocess_platform import (
    harden_windows_stdio_argv,
    prefer_windows_gui_safe_executable,
    subprocess_hide_window_kwargs,
    wrap_windows_batch_argv,
)


def test_subprocess_hide_window_kwargs_empty_off_windows() -> None:
    if os.name == "nt":
        kwargs = subprocess_hide_window_kwargs()
        assert "creationflags" in kwargs or "startupinfo" in kwargs
    else:
        assert subprocess_hide_window_kwargs() == {}


@pytest.mark.skipif(os.name != "nt", reason="Windows-only batch wrap")
def test_wrap_windows_batch_argv_routes_cmd_through_comspec() -> None:
    cmd, args = wrap_windows_batch_argv(r"C:\tools\npx.cmd", ["-y", "foo"])
    assert cmd.lower().endswith("cmd.exe") or Path(cmd).name.lower() == "cmd.exe"
    assert args[:3] == ["/d", "/c", r"C:\tools\npx.cmd"]
    assert args[3:] == ["-y", "foo"]


@pytest.mark.skipif(os.name != "nt", reason="Windows-only batch wrap")
def test_wrap_windows_batch_argv_leaves_exe_alone() -> None:
    cmd, args = wrap_windows_batch_argv(r"C:\tools\node.exe", ["a.js"])
    assert cmd == r"C:\tools\node.exe"
    assert args == ["a.js"]


@pytest.mark.skipif(os.name != "nt", reason="Windows-only")
def test_prefer_windows_gui_safe_executable_prefers_exe_sibling(tmp_path: Path) -> None:
    bat = tmp_path / "tool.cmd"
    exe = tmp_path / "tool.exe"
    bat.write_text("@echo off\n", encoding="utf-8")
    exe.write_text("", encoding="utf-8")
    with patch("evoflow.utils.subprocess_platform.shutil.which", return_value=str(bat)):
        assert prefer_windows_gui_safe_executable("tool") == str(exe)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only")
def test_harden_windows_stdio_argv_wraps_cmd_shim(tmp_path: Path) -> None:
    bat = tmp_path / "weird.cmd"
    bat.write_text("@echo off\n", encoding="utf-8")
    with patch("evoflow.utils.subprocess_platform.shutil.which", return_value=str(bat)):
        cmd, args = harden_windows_stdio_argv("weird", ["--flag"])
    assert Path(cmd).name.lower() == "cmd.exe" or cmd.lower().endswith("cmd.exe")
    assert "/d" in args and "/c" in args
    assert str(bat) in args
    assert args[-1] == "--flag"


def test_harden_windows_stdio_argv_noop_on_posix() -> None:
    if os.name == "nt":
        pytest.skip("posix behavior")
    cmd, args = harden_windows_stdio_argv("npx", ["-y", "pkg"])
    assert cmd == "npx"
    assert args == ["-y", "pkg"]


@pytest.mark.skipif(sys.platform != "win32", reason="MCP patch is Windows-only")
def test_patch_mcp_stdio_no_console_flash_idempotent() -> None:
    from evoflow.utils.subprocess_platform import patch_mcp_stdio_no_console_flash

    first = patch_mcp_stdio_no_console_flash()
    second = patch_mcp_stdio_no_console_flash()
    # True when mcp is installed; False when missing — either way must be stable.
    assert first == second
    if first:
        from mcp.os.win32 import utilities as win_util

        assert getattr(win_util, "_evoflow_no_console_flash", False) is True

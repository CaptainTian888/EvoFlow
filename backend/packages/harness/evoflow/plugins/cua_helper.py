r"""ZCode CUA helper runtime for EvoFlow — discovery, self-healing copy, kernel env.

ZCode 的 14 个电脑控制工具面实现在 node-repl-host 的 broker 模块里，helper
（windows-helper.js + ax_native.node 原生插件）只提供底层原语（UIA 读写、截图、
SendInput、应用枚举与图标提取）。宿主 broker 的激活条件是两个环境变量：

  - ``ZCODE_CUA_PERMISSION_BROKER_SOCKET`` — helper 监听的命名管道
    （宿主校验管道名必须落在 ``\\.\pipe\zcode-cua-helper-`` 命名空间内）。
  - ``ZCODE_CUA_WIN_HELPER_RECIPE`` — helper fork 配方 JSON（command / entryPath /
    root / addonPath / commandEnv / hostPid）。宿主在连接失败时按配方 detached
    拉起 helper：``<command> <entryPath> --socket <pipe> --parent-pid <hostPid>``。

本模块沿用 node-repl-host 的“本地运行时自愈复制”模式：优先 EvoFlow 自己的插件
缓存副本，缺失时从本机 ZCode 桌面安装（``resources/tools/cua-helper``）复制一份；
都不可用则返回 None，调用方回退到 v1 视觉桥（cua_exec.ps1）。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HELPER_RUNTIME_DIRNAME = "cua-helper"
HELPER_ENTRY_REL = ("dist", "windows-helper.js")
HELPER_ADDON_REL = ("build", "Release", "ax_native.node")

_SOCKET_ENV = "ZCODE_CUA_PERMISSION_BROKER_SOCKET"
_RECIPE_ENV = "ZCODE_CUA_WIN_HELPER_RECIPE"
# 宿主校验：管道必须落在 zcode-cua-helper 命名空间内（server.js 的
# WIN32_NAMED_PIPE_NAME_RE，要求 8 位以上 hex 或 "default"）。
_SOCKET_NAMESPACE = "\\\\.\\pipe\\zcode-cua-helper-"


def _helper_entry(root: Path) -> Path:
    return root.joinpath(*HELPER_ENTRY_REL)


def _helper_addon(root: Path) -> Path:
    return root.joinpath(*HELPER_ADDON_REL)


def is_helper_runtime(root: Path) -> bool:
    return _helper_entry(root).is_file() and _helper_addon(root).is_file()


# ---------------------------------------------------------------------------
# 发现
# ---------------------------------------------------------------------------


def discover_zcode_desktop_root() -> Path | None:
    """Locate the local ZCode desktop install root (containing ``resources``)."""
    override = os.getenv("EVOFLOW_ZCODE_DESKTOP_ROOT", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    candidates.extend(_registry_install_roots())
    program_files = os.getenv("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.getenv("ProgramFiles(x86)", "C:\\Program Files (x86)")
    local_appdata = os.getenv("LOCALAPPDATA", "")
    for base in (program_files, program_files_x86):
        candidates.append(Path(base) / "ZCode")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Programs" / "zcode")
        candidates.append(Path(local_appdata) / "Programs" / "ZCode")
    for candidate in candidates:
        try:
            if (candidate / "resources" / "tools" / "cua-helper").is_dir():
                return candidate
        except OSError:
            continue
    return None


def _registry_install_roots() -> list[Path]:
    """Read ZCode's NSIS uninstall entry (DisplayName contains "ZCode")."""
    roots: list[Path] = []
    try:
        import winreg
    except ImportError:
        return roots
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0,) if hive == winreg.HKEY_CURRENT_USER else (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                key = winreg.OpenKey(
                    hive,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                    0,
                    winreg.KEY_READ | view,
                )
            except OSError:
                continue
            with key:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            display, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            if "zcode" not in str(display).lower():
                                continue
                            for value_name in ("InstallLocation", "DisplayIcon"):
                                try:
                                    value, _ = winreg.QueryValueEx(subkey, value_name)
                                except OSError:
                                    continue
                                text = str(value).split(",")[0].strip().strip('"')
                                if not text:
                                    continue
                                path = Path(text)
                                # InstallLocation 是目录；DisplayIcon/UninstallString 是
                                # 文件（.ico/.exe），取其父目录作为安装根。
                                root = path.parent if path.suffix else path
                                if root.name.lower() in {"", "windows"}:
                                    continue
                                if root not in roots:
                                    roots.append(root)
                    except OSError:
                        continue
    return roots


def resolve_helper_runtime(storage_root: Path | None = None) -> Path | None:
    """Resolve a usable helper runtime root; self-heal a copy into the EvoFlow cache."""
    override = os.getenv("EVOFLOW_CUA_HELPER_ROOT", "").strip()
    if override:
        root = Path(override)
        if is_helper_runtime(root):
            return root
        logger.warning("EVOFLOW_CUA_HELPER_ROOT does not contain a helper runtime: %s", root)

    if storage_root is None:
        try:
            from .storage import resolve_storage_root

            storage_root = resolve_storage_root()
        except Exception:  # noqa: BLE001
            storage_root = Path.home() / ".evoflow" / "data" / "plugins"
    cache_copy = Path(storage_root) / "cache" / "evoflow-plugins-official" / HELPER_RUNTIME_DIRNAME / "runtime"
    if is_helper_runtime(cache_copy):
        return cache_copy

    desktop_root = discover_zcode_desktop_root()
    if desktop_root is None:
        return None
    source = desktop_root / "resources" / "tools" / "cua-helper"
    if not is_helper_runtime(source):
        return None
    try:
        cache_copy.parent.mkdir(parents=True, exist_ok=True)
        if cache_copy.exists():
            shutil.rmtree(cache_copy, ignore_errors=True)
        shutil.copytree(
            source,
            cache_copy,
            ignore=shutil.ignore_patterns(".git", "*.log"),
        )
        logger.info("cua-helper runtime copied from ZCode install %s → %s", source, cache_copy)
        return cache_copy
    except OSError:
        logger.warning("cua-helper copy into plugin cache failed", exc_info=True)
        # 安装目录仍可直接运行（只读引用），复制失败不阻断。
        return source if is_helper_runtime(source) else None


# ---------------------------------------------------------------------------
# 内核环境注入
# ---------------------------------------------------------------------------


def _resolve_node_command() -> str:
    override = os.getenv("EVOFLOW_NODE_COMMAND", "").strip()
    if override:
        return override
    from shutil import which

    return which("node") or "node"


def build_kernel_env(helper_root: Path, host_pid: int | None = None) -> dict[str, str]:
    """Env overlay that activates the node-repl-host's own CUA broker + helper."""
    pipe = f"{_SOCKET_NAMESPACE}{secrets.token_hex(8)}"
    recipe: dict[str, Any] = {
        "command": _resolve_node_command(),
        "entryPath": str(_helper_entry(helper_root)),
        "root": str(helper_root),
        "addonPath": str(_helper_addon(helper_root)),
        "commandEnv": {},
        # helper 的 liveness watchdog 盯这个 pid；宿主进程 pid 要等内核起来才知道，
        # 这里用网关进程——网关退出 helper 随之退出，语义等价。
        "hostPid": int(host_pid or os.getpid()),
    }
    return {
        _SOCKET_ENV: pipe,
        _RECIPE_ENV: json.dumps(recipe, ensure_ascii=False),
    }


def kernel_env_overlay(storage_root: Path | None = None) -> dict[str, str]:
    """Full overlay for the node_repl kernel; {} when no helper runtime is available."""
    try:
        helper_root = resolve_helper_runtime(storage_root)
        if helper_root is None:
            return {}
        overlay = build_kernel_env(helper_root)
        logger.info(
            "cua helper runtime active: root=%s socket=%s",
            helper_root,
            overlay[_SOCKET_ENV],
        )
        return overlay
    except Exception:  # noqa: BLE001
        logger.warning("cua helper env overlay failed; falling back to visual bridge", exc_info=True)
        return {}


def helper_runtime_status(storage_root: Path | None = None) -> dict[str, Any]:
    """Diagnostic view for the settings/plugin pages."""
    helper_root = resolve_helper_runtime(storage_root)
    return {
        "available": helper_root is not None,
        "root": str(helper_root) if helper_root else None,
        "entry": str(_helper_entry(helper_root)) if helper_root else None,
        "addon": str(_helper_addon(helper_root)) if helper_root else None,
        "platform_ok": sys.platform == "win32",
    }

r"""CUA helper runtime for EvoFlow — discovery, self-healing copy, kernel env.

电脑控制工具面由 node-repl-host broker 提供；helper（windows-helper.js +
ax_native.node）只做底层原语（UIA / 截图 / SendInput / 应用枚举）。宿主 broker
激活依赖：

  - ``ZCODE_CUA_PERMISSION_BROKER_SOCKET`` — helper 命名管道
    （须落在 ``\\.\pipe\zcode-cua-helper-`` 命名空间）。
  - ``ZCODE_CUA_WIN_HELPER_RECIPE`` — helper fork 配方 JSON。

解析顺序：``EVOFLOW_CUA_HELPER_ROOT`` → 已缓存副本 → 安装包
``official-plugins-bundle/cua-helper``。都不可用则返回 None，调用方回退 v1
视觉桥（cua_exec.ps1）。
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

    from .builtin import discover_bundled_official_cache

    bundle = discover_bundled_official_cache()
    source: Path | None = None
    if bundle is not None:
        for candidate in (
            bundle / HELPER_RUNTIME_DIRNAME / "runtime",
            bundle / HELPER_RUNTIME_DIRNAME,
        ):
            if is_helper_runtime(candidate):
                source = candidate
                break
    if source is None:
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
        logger.info("cua-helper runtime copied from packaged bundle %s → %s", source, cache_copy)
        return cache_copy
    except OSError:
        logger.warning("cua-helper copy into plugin cache failed", exc_info=True)
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

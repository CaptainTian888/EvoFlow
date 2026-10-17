"""统一浏览器调试日志（三端汇聚到一个文件）。

排查「两个浏览器窗口 / 面板不贴合 / 导航不显示」这类问题时，日志散在
Rust stderr、Python logging、前端 console 三处，时间线对不上。本模块把
所有浏览器相关日志追加到同一个文件：

    {evoflow_dir}/插件控制日志.log

写入方：
- Rust:  ``browser_cdp_server::log_line``（窗口生命周期/CDP 分发，前缀 ``[rust]``）
- Python: :func:`browser_debug_log`（引擎/网关路由，前缀 ``[py]``）以及
  :func:`install_browser_debug_mirror` 把包含 "browser" 的 logging 记录镜像进来
- 前端:  ``POST /api/browser/log``（面板/早处理器上报，前缀 ``[web]``）

evoflow_dir 与 Rust ``commands::evoflow_dir`` 保持一致：
``EVOFLOW_CONFIG_DIR`` > ``~/.evoflow-dev``（存在时） > ``~/.evoflow``。
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path

_FILE_NAME = "插件控制日志.log"
_WRITE_LOCK = threading.Lock()


def unified_log_path() -> Path:
    """与 Rust ``evoflow_dir()`` 相同的目录下的 插件控制日志.log。"""
    env = os.environ.get("EVOFLOW_CONFIG_DIR")
    if env:
        base = Path(env)
    else:
        home = Path(os.path.expanduser("~"))
        debug_dir = home / ".evoflow-dev"
        # 与 browser_engine._resolve_evoflow_dir 相同的探测顺序：
        # debug 构建的桌面端写 ~/.evoflow-dev，release 写 ~/.evoflow。
        base = debug_dir if debug_dir.is_dir() else home / ".evoflow"
    return base / _FILE_NAME


def browser_debug_log(source: str, message: str) -> None:
    """追加一行到统一日志。任何失败都静默——日志永远不能打断业务。"""
    try:
        line = f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]} [{source}] {message}\n"
        path = unified_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        pass


class _BrowserMirrorHandler(logging.Handler):
    """把 Python logging 里浏览器/插件相关的记录镜像进统一文件。

    命中规则：logger 名含 ``browser`` / ``node_repl`` / ``plugins`` / ``cua``，
    或消息文本含 ``browser``。evoflow.plugins.* 的记录本身就是插件使用事件。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            name = record.name.lower()
            msg = record.getMessage()
            relevant = (
                "browser" in name
                or "node_repl" in name
                or "plugins" in name
                or "cua" in name
                or "browser" in msg.lower()
            )
            if not relevant:
                return
            browser_debug_log("py", f"{record.name}: {msg}")
        except Exception:
            pass


def _mirror_is_attached() -> bool:
    root = logging.getLogger()
    return any(isinstance(h, _BrowserMirrorHandler) for h in root.handlers)


def install_browser_debug_mirror() -> None:
    """挂到 root logger。幂等且可自愈。

    LangGraph 在 lifespan 里用 dictConfig 重建日志树（disable_existing_loggers
    + 替换 root handlers），会把这里挂的 handler 摘掉、把引擎 logger 置为
    disabled。因此除了启动时调用，浏览器路由的每个入口也应调用本函数——
    发现 handler 不在或目标 logger 被 disable 时自动恢复。
    """
    root = logging.getLogger()
    if not _mirror_is_attached():
        root.addHandler(_BrowserMirrorHandler(level=logging.INFO))
    # 网关根级别可能是 WARNING；引擎/桥路由的浏览器日志大多是 INFO。
    for name in (
        "evoflow.tools.builtins.browser_engine",
        "app.gateway.routers.browser_bridge",
        "app.gateway.routers.cua_bridge",
        "evoflow.plugins.node_repl",
        "evoflow.plugins.node_repl_tool",
        "evoflow.plugins.service",
        "evoflow.plugins.runtime",
    ):
        logger = logging.getLogger(name)
        if logger.disabled:
            logger.disabled = False
        if logger.getEffectiveLevel() > logging.INFO or logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)
    _MIRROR_INSTALLED = True

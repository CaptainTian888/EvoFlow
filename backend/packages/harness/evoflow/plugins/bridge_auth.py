"""Browser/CUA bridge token（对齐 ZCode broker-token 鉴权语义）.

node-repl 内核桥经本地 HTTP 调 Gateway 的浏览器/CUA 命令面（``/api/browser/execute``
等）。这些端点此前依赖 ``http_guard.require_org_admin`` 的"本地无凭据 → 管理员"
单用户旁路——内核里模型生成的任意 JS、乃至本机任意进程都能触达网关命令面。
本模块提供进程稳定的共享令牌：

- 网关侧读或生成持久化 token（数据目录下 ``bridge-token``，重启后不变，
  避免网关重启令旧内核 env 失效）；
- ``node_repl.py`` spawn host 时经 ``EVOFLOW_BROWSER_BRIDGE_TOKEN`` 注入内核；
- 桥 JS（``_BRIDGE_SETUP_JS``）每次请求携带 ``X-EvoFlow-Bridge-Token`` 头；
- 命令面路由用 :func:`verify_bridge_token` 强制校验（缺失/不匹配 → 403）。
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading

logger = logging.getLogger(__name__)

_BRIDGE_TOKEN_ENV = "EVOFLOW_BROWSER_BRIDGE_TOKEN"
_BRIDGE_TOKEN_HEADER = "x-evoflow-bridge-token"
_TOKEN_FILE_NAME = "bridge-token"

_token_cache: str | None = None
_token_lock = threading.Lock()


def _token_file_path() -> str:
    # EVOFLOW_BRIDGE_TOKEN_FILE：测试/多实例部署显式指定 token 落盘位置。
    override = os.environ.get("EVOFLOW_BRIDGE_TOKEN_FILE", "").strip()
    if override:
        return override
    from evoflow.config.data_paths import resolve_data_base_dir

    return os.path.join(str(resolve_data_base_dir()), _TOKEN_FILE_NAME)


def reset_bridge_token_cache() -> None:
    """清空进程内 token 缓存（测试隔离用；生产不需要）。"""
    global _token_cache
    with _token_lock:
        _token_cache = None


def get_bridge_token() -> str:
    """读或生成持久化 bridge token（进程内缓存 + 落盘）。"""
    global _token_cache
    with _token_lock:
        if _token_cache:
            return _token_cache
        env_token = os.environ.get(_BRIDGE_TOKEN_ENV, "").strip()
        if env_token:
            _token_cache = env_token
            return _token_cache
        path = _token_file_path()
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    existing = fh.read().strip()
                if existing:
                    _token_cache = existing
                    return _token_cache
            token = secrets.token_urlsafe(32)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(token)
            logger.info("Browser bridge token generated at %s", path)
            _token_cache = token
            return _token_cache
        except OSError as exc:
            # 落盘失败（只读 FS 等）退回进程内随机 token：网关与 node_repl 同进程
            # 时依然一致；跨进程场景退化为无 token（保持可用性优先）。
            logger.warning("Bridge token file unavailable (%s); using in-process token", exc)
            _token_cache = secrets.token_urlsafe(32)
            return _token_cache


def verify_bridge_token(request) -> bool:
    """校验请求头里的 bridge token；缺失或不匹配一律拒绝。

    内核桥是这些端点的唯一预期调用方（面板控制走 Tauri 命令、日志走 /api/browser/log，
    均不在 token 范围内），因此强制校验不构成兼容性负担。外部集成方从数据目录的
    ``bridge-token`` 文件读取令牌。
    """
    expected = get_bridge_token()
    supplied = str(request.headers.get(_BRIDGE_TOKEN_HEADER) or "").strip()
    if not supplied:
        return False
    return hmac.compare_digest(supplied, expected)

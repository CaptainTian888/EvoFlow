"""EvoFlow host for the ZCode ``node_repl`` kernel (Browser Use / Computer Use).

The official plugins' skills (``control-browser`` / ``computer-use``) hard-require
a ``mcp__node_repl__js`` tool that executes JavaScript inside the node-repl-host
kernel, where the Browser Use and Computer Use bridges live. The host speaks the
MCP "modern era" protocol (2026-07-28) which the Python MCP SDK cannot yet
negotiate, so this module drives it with raw JSON-RPC over stdio, carrying the
required ``_meta`` envelope on every message.

The tool is registered only when one of the dependent plugins is installed and
enabled, and the host runtime exists in the plugin cache.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ulog(message: str) -> None:
    """统一浏览器/插件调试日志（browser-debug.log，三端汇聚）。"""
    try:
        from evoflow.tools.builtins.browser_debug_log import browser_debug_log

        browser_debug_log("py", f"[node-repl] {message}")
    except Exception:
        pass

_NODE_REPL_HOST_PLUGIN = "node-repl-host"
_BROWSER_USE_PLUGIN = "browser-use"
_COMPUTER_USE_PLUGIN = "computer-use"
_NODE_REPL_SERVER_REL = "dist/mcp/server.js"
_PROTOCOL_VERSION = "2026-07-28"
_META_KEY = "io.modelcontextprotocol/protocolVersion"
_CALL_TIMEOUT_SEC = 130

# ---------------------------------------------------------------------------
# 浏览器桥（browser-use 插件 control-browser 技能的执行底座）
# 契约：node-repl-host/src/runtime-bridge.ts —
#   globalThis[Symbol.for("zcode.node-repl.browser-control-bridge")] =
#     { list(): BrowserInfo[]; execute(browserId, generation, command): CommandResult;
#       documentationRoot: string; assertAvailable(): void }
# 命令词表 = ZCode browser command contract（EvoFlow browser_engine 原生支持）。
# ---------------------------------------------------------------------------

_BRIDGE_SETUP_JS = r"""
const __evoflowBridgeSymbol = Symbol.for("zcode.node-repl.browser-control-bridge");
{
  // 无条件覆盖：宿主自带的桥依赖 ZCode 桌面 broker（无桌面即不可用），
  // EvoFlow 平台桥是本环境权威 provider，必须接管该全局。
  const __gwPort = process.env.EVOFLOW_GATEWAY_PORT || "8070";
  const __gwBase = `http://127.0.0.1:${__gwPort}`;
  // 浏览器/CUA 命令面共享令牌：网关 _bridge_token_guard 强制校验（缺头/不匹配 → 403）。
  const __bridgeToken = process.env.EVOFLOW_BROWSER_BRIDGE_TOKEN || "";
  // 内核 worker 是受限环境：无全局 fetch，只能用 node:* 内置模块。
  const __gwFetch = async (path, init) => {
    const http = await import("node:http");
    const body = init?.body ?? null;
    const result = await new Promise((resolve, reject) => {
      const req = http.request(
        `${__gwBase}${path}`,
        {
          method: init?.method || (body ? "POST" : "GET"),
          headers: {
            "Content-Type": "application/json",
            "X-EvoFlow-Bridge-Token": __bridgeToken,
            ...(body ? { "Content-Length": String(Buffer.byteLength(body)) } : {}),
            ...(init?.headers || {}),
          },
        },
        (res) => {
          let data = "";
          res.setEncoding("utf8");
          res.on("data", (chunk) => { data += chunk; });
          res.on("end", () => resolve({ status: res.statusCode, text: data }));
        },
      );
      req.on("error", reject);
      if (body) req.write(body);
      req.end();
    });
    if (result.status < 200 || result.status >= 300) {
      throw new Error(`EvoFlow browser bridge HTTP ${result.status}: ${result.text.slice(0, 300)}`);
    }
    return JSON.parse(result.text);
  };
  const __docsRoot = process.env.EVOFLOW_BROWSER_DOCS_ROOT || "";
  const __unavailable = (detail) => {
    throw new Error(
      "Browser runtime bridge is unavailable: EvoFlow Gateway browser service unreachable" +
      (detail ? ` (${detail})` : ""),
    );
  };
  // 探测带重试：网关重启窗口/端口双绑定切换时会偶发 403/404/ECONNREFUSED，
  // 单次探测就把整个 MCP 首调打死。3 次 × 250ms 退避，并把最后一次的
  // 真实状态带回给调用方（统一日志也能看到原因）。
  const __probe = async (path) => {
    let lastErr = "";
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        return await __gwFetch(path);
      } catch (err) {
        lastErr = String((err && err.message) || err).slice(0, 200);
        if (attempt < 3) {
          await new Promise((r) => setTimeout(r, 250 * attempt));
        }
      }
    }
    __unavailable(`${lastErr} (gw=${__gwBase}, 3 attempts)`);
  };
  const __assert = async () => {
    const info = await __probe("/api/browser/transport");
    const transport = (info && info.transport) || "unknown";
    // 用户要求：只驱动客户端内置浏览器面板（webview2）；系统 Edge 回退不可接受。
    if (transport !== "webview2") {
      throw new Error(
        `EvoFlow 内置浏览器面板（WebView2）当前不可用，桌面端已回退到系统 Edge（transport=${transport}）。` +
        "按平台要求不驱动 Edge——请在 EvoFlow 桌面端重启应用以恢复内置浏览器面板，然后重试。",
      );
    }
  };
  // facade 命令 → EvoFlow engine 命令映射（显式白名单，未列出即结构化报错）
  const __direct = new Set([
    "navigate", "back", "forward", "reload", "snapshot", "click", "fill", "type",
    "press", "scroll", "hover", "select", "check", "drag", "screenshot",
    "getState", "elementInfo", "evaluate", "waitFor", "close", "list",
  ]);
  const __map = {
    browserViewportSet: (command) => ({ method: "viewportSet", width: command.width, height: command.height }),
    newTab: (command) => ({ method: "navigate", url: command.url }),
    activateTab: () => ({ method: "getState" }),
    claimTab: (command, browserId) => ({
      method: "getState",
      tabId: "primary",
      __tab: { id: "primary", url: "", title: "EvoFlow WebView", viewport: { width: 1280, height: 720 }, active: true, lifecycle: "active" },
    }),
    getDialog: () => ({ method: "getState", __dialog: null }),
    handleDialog: (command) => ({ method: "getState", __dialog: null }),
  };
  const __unsupported = (name) => ({
    ok: false,
    error: { code: "unsupported", message: `EvoFlow browser bridge v1 不支持命令: ${name}（录屏/桌面控制属后续平台集成）`, sideEffect: "none" },
  });
  // 命令日志：每次浏览器命令的 method/url/结果状态，供工具结果回传给模型与排查
  globalThis.__evoflowBrowserLog = [];
  const __logCmd = (entry) => {
    try {
      globalThis.__evoflowBrowserLog.push({ ts: Date.now(), ...entry });
      if (globalThis.__evoflowBrowserLog.length > 50) globalThis.__evoflowBrowserLog.shift();
    } catch {}
  };
  globalThis[__evoflowBridgeSymbol] = {
    documentationRoot: __docsRoot,
    assertAvailable: __assert,
    async list() {
      const body = await __gwFetch("/api/browser/tabs");
      const tab = (body.tabs || [])[0] || {};
      __logCmd({ kind: "list", url: tab.url, ok: true });
      return [{
        id: "evoflow-webview",
        type: "iab",
        active: true,
        capabilities: [{ id: "visibility", description: "Show or hide the browser pane" }],
        metadata: { source: "evoflow-gateway", url: tab.url, title: tab.title, viewport: tab.viewport },
      }];
    },
    async execute(_browserId, _generation, command) {
      await __assert();
      // ZCode 运行时（browser-client.mjs 的 BrowsersFacade）用 { method, params: {...} }
      // 嵌套形状；EvoFlow 引擎契约是平铺字段。这里统一解包 params 再透传，
      // 否则 navigate/screenshot 等全部报 "requires url"。
      const cmd = command && typeof command.params === "object" && command.params !== null
        ? { ...command, ...command.params }
        : command;
      const name = cmd?.method || "";
      const url = cmd?.url || "";
      try {
        let result;
        if (__direct.has(name)) {
          result = await __gwFetch("/api/browser/execute", { method: "POST", body: JSON.stringify({ command: cmd }) });
        } else if (__map[name]) {
          const mapped = __map[name](cmd, _browserId);
          result = await __gwFetch("/api/browser/execute", { method: "POST", body: JSON.stringify({ command: mapped }) });
          if (mapped.__tab) result.tab = mapped.__tab;
          if ("__dialog" in mapped) result.dialog = mapped.__dialog;
        } else {
          result = __unsupported(name);
        }
        __logCmd({ kind: name, url, ok: result?.ok !== false });
        return result;
      } catch (err) {
        __logCmd({ kind: name, url, ok: false, error: String(err).slice(0, 160) });
        throw err;
      }
    },
  };
  // ── CUA 桥（computer-use 插件）：覆盖宿主自带的死桥（本构建 CUA fail-closed）──
  const __cuaSymbol = Symbol.for("zcode.node-repl.computer-use-bridge");
  globalThis[__cuaSymbol] = {
    documentationRoot: __docsRoot,
    assertAvailable: async () => {},
    call: async (method, methodInput) => {
      try {
        const resp = await __gwFetch("/api/cua/execute", {
          method: "POST",
          body: JSON.stringify({ method, input: methodInput || {} }),
        });
        __logCmd({ kind: `cua:${method}`, ok: resp?.ok !== false });
        return resp; // CallToolResult 形状（content / isError）
      } catch (err) {
        __logCmd({ kind: `cua:${method}`, ok: false, error: String(err).slice(0, 160) });
        throw err;
      }
    },
  };
}
"""

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_next_id = 3  # ids 1/2 reserved for the probe-free startup
_responses: dict[int, dict[str, Any]] = {}
_reader_thread: threading.Thread | None = None


def _meta_envelope() -> dict[str, Any]:
    # session_id：宿主浏览器桥用它做会话绑定（requestContext）；单桌面单会话语义。
    return {
        _META_KEY: _PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {"tools": {}},
        "io.modelcontextprotocol/clientInfo": {"name": "evoflow", "version": "1.0.0"},
        "session_id": "evoflow-main",
        "runtime_scope": "main",
    }


def resolve_host_server_js(storage_root: Path | None = None) -> Path | None:
    """Locate ``dist/mcp/server.js`` from the node-repl-host install cache.

    node-repl-host 不出现在市场清单（ZCode 同款语义：宿主不对用户露出）。
    首次需要时从本机 ZCode 安装的官方缓存自愈复制到 EvoFlow 插件缓存。
    """
    try:
        if storage_root is None:
            from .storage import resolve_storage_root

            storage_root = resolve_storage_root()
        cache_root = storage_root / "cache" / "evoflow-plugins-official" / _NODE_REPL_HOST_PLUGIN
        if not cache_root.is_dir():
            _ensure_host_runtime_copied(storage_root, cache_root)
        version_dirs = sorted(
            (d for d in cache_root.iterdir() if d.is_dir()),
            key=lambda d: [int(part) if part.isdigit() else 0 for part in d.name.split(".")],
        ) if cache_root.is_dir() else []
        for version_dir in reversed(version_dirs):
            candidate = version_dir / _NODE_REPL_SERVER_REL
            if candidate.is_file():
                return candidate
    except Exception:  # noqa: BLE001
        logger.debug("node-repl-host resolution failed", exc_info=True)
    return None


def _ensure_host_runtime_copied(storage_root: Path, cache_root: Path) -> None:
    """Copy node-repl-host from the local ZCode installation cache (self-healing)."""
    import shutil

    from .builtin import discover_zcode_official_cache

    zcode_root = discover_zcode_official_cache()
    if zcode_root is None:
        return
    host_dir = zcode_root / _NODE_REPL_HOST_PLUGIN
    if not host_dir.is_dir():
        return
    version_dirs = sorted(
        (d for d in host_dir.iterdir() if d.is_dir()),
        key=lambda d: [int(part) if part.isdigit() else 0 for part in d.name.split(".")],
    )
    for version_dir in reversed(version_dirs):
        if (version_dir / _NODE_REPL_SERVER_REL).is_file():
            cache_root.mkdir(parents=True, exist_ok=True)
            target = cache_root / version_dir.name
            if not (target / _NODE_REPL_SERVER_REL).is_file():
                shutil.copytree(version_dir, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
                logger.info("node-repl-host runtime copied from EvoFlow cache: %s", target)
            return


def is_node_repl_available(storage_root: Path | None = None) -> bool:
    """The ``mcp__node_repl__js`` tool is offered when a dependent official
    plugin (browser-use / computer-use) is installed + enabled and the host
    runtime is present."""
    try:
        if resolve_host_server_js(storage_root) is None:
            return False
        from .storage import InstalledPluginsState, load_installed_plugins_state

        storage = (
            Path(storage_root)
            if storage_root
            else __import__("evoflow.plugins.storage", fromlist=["resolve_storage_root"]).resolve_storage_root()
        )
        state = load_installed_plugins_state(storage)
        for record in state.plugins:
            if record.name in ("browser-use", "computer-use") and state.is_enabled(record.id):
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def _pump_stdout(proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        request_id = message.get("id")
        if isinstance(request_id, int):
            _responses[request_id] = message


def _latest_plugin_root(storage_root: Path, plugin_name: str) -> Path | None:
    """Latest installed version dir for a plugin (for plugin-root env injection)."""
    cache_root = Path(storage_root) / "cache" / "evoflow-plugins-official" / plugin_name
    if not cache_root.is_dir():
        return None
    version_dirs = sorted(
        (d for d in cache_root.iterdir() if d.is_dir()),
        key=lambda d: [int(p) if p.isdigit() else 0 for p in d.name.split(".")],
    )
    return version_dirs[-1] if version_dirs else None


def _ensure_process() -> subprocess.Popen:
    global _proc, _reader_thread
    if _proc is not None and _proc.poll() is None:
        return _proc
    from .storage import resolve_storage_root

    server_js = resolve_host_server_js(resolve_storage_root())
    if server_js is None:
        raise RuntimeError("node-repl-host runtime is not available in the plugin cache")
    _responses.clear()
    from .storage import resolve_storage_root as _rsr

    storage_root = _rsr()
    kernel_env = dict(os.environ)
    kernel_env.setdefault("EVOFLOW_GATEWAY_PORT", os.getenv("EVOFLOW_GATEWAY_PORT", "8070"))
    # 浏览器/CUA 桥命令面共享令牌：桥 JS 每次请求携带 X-EvoFlow-Bridge-Token 头，
    # 网关 _bridge_token_guard 强制校验（bridge_auth，持久化 token 重启稳定）。
    try:
        from .bridge_auth import get_bridge_token

        kernel_env["EVOFLOW_BROWSER_BRIDGE_TOKEN"] = get_bridge_token()
    except Exception:
        logger.warning("bridge token unavailable; kernel bridge requests may be rejected", exc_info=True)
    # 官方插件技能的 bootstrap 依赖插件根目录 env（control-browser 读
    # ZCODE_PLUGIN_ROOT/scripts/browser-client.mjs；computer-use 读
    # ZCODE_CUA_PLUGIN_ROOT/scripts/computer-use-client.mjs）。
    for plugin_name, env_key in (
        (_BROWSER_USE_PLUGIN, "ZCODE_PLUGIN_ROOT"),
        (_BROWSER_USE_PLUGIN, "CLAUDE_PLUGIN_ROOT"),
        (_COMPUTER_USE_PLUGIN, "ZCODE_CUA_PLUGIN_ROOT"),
    ):
        if not kernel_env.get(env_key):
            plugin_root = _latest_plugin_root(storage_root, plugin_name)
            if plugin_root:
                kernel_env[env_key] = str(plugin_root)
    _proc = subprocess.Popen(
        ["node", str(server_js)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        cwd=str(server_js.parent),
        env=kernel_env,
    )
    _reader_thread = threading.Thread(target=_pump_stdout, args=(_proc,), daemon=True)
    _reader_thread.start()
    logger.info("node-repl-host kernel started: %s", server_js)
    return _proc


def _request(method: str, params: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    global _next_id
    with _lock:
        proc = _ensure_process()
        request_id = _next_id
        _next_id += 1
        params = {**params, "_meta": _meta_envelope()}
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if request_id in _responses:
                return _responses.pop(request_id)
            if proc.poll() is not None:
                raise RuntimeError("node-repl-host kernel exited unexpectedly")
            time.sleep(0.05)
        raise TimeoutError(f"node-repl-host {method} timed out after {timeout_sec}s")


def call_node_repl_js(code: str, timeout_ms: int = 120_000) -> str:
    """Execute JavaScript in the node-repl-host kernel; returns the text result.

    每次 call 都先注入浏览器桥 setup（幂等 ``??=``）：control-browser 技能的
    bootstrap 读取 ``Symbol.for("zcode.node-repl.browser-control-bridge")``，
    桥用 fetch 把 ZCode 浏览器命令转发给 EvoFlow Gateway（本地请求免鉴权）。
    """
    started = time.monotonic()
    preview = " ".join(code.split())[:160]
    _ulog(f"js call start ({len(code)} chars): {preview}")
    try:
        response = _request(
            "tools/call",
            {"name": "js", "arguments": {"code": _BRIDGE_SETUP_JS + "\n" + code, "timeout_ms": min(int(timeout_ms), 120_000)}},
            timeout_sec=timeout_ms / 1000 + 15,
        )
    except Exception as exc:
        _ulog(f"js call FAILED after {time.monotonic() - started:.1f}s: {exc}")
        raise
    if "error" in response:
        _ulog(f"js call jsonrpc error: {json.dumps(response['error'], ensure_ascii=False)[:200]}")
        raise RuntimeError(f"node_repl js error: {json.dumps(response['error'], ensure_ascii=False)[:400]}")
    result = response.get("result") or {}
    if result.get("isError"):
        parts = [
            str(part.get("text") or "")
            for part in result.get("content") or []
            if isinstance(part, dict)
        ]
        message = "node_repl js failed: " + "\n".join(parts)[:800]
        _ulog(f"js call isError after {time.monotonic() - started:.1f}s: {message[:200]}")
        raise RuntimeError(message)
    parts = [
        str(part.get("text") or "")
        for part in result.get("content") or []
        if isinstance(part, dict)
    ]
    text = "\n".join(parts)
    _ulog(f"js call ok in {time.monotonic() - started:.1f}s, result {len(text)} chars: {' '.join(text.split())[:120]}")
    return text


def shutdown() -> None:
    global _proc
    with _lock:
        if _proc is not None and _proc.poll() is None:
            _proc.kill()
        _proc = None

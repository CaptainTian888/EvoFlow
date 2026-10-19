"""Browser bridge tests — real node kernel + real loopback HTTP stub.

Verifies the embedded ``BRIDGE_SETUP_JS`` adapter end to end: the bridge global
registers under the ZCode symbol, ``list()`` and ``execute(command)`` reach the
Gateway HTTP surface, the command mapping table routes correctly, and
unmapped commands return structured errors.
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import json as _json
import pytest


def parse_kernel_json(out: str):
    """Kernel returns ``=> <value>``; object values arrive as JSON-encoded strings."""
    value = _json.loads(out.removeprefix("=> ").strip())
    if isinstance(value, str):
        value = _json.loads(value)
    return value


gateway_stub_transport: dict = {"value": "webview2"}


@pytest.fixture(scope="module")
def gateway_stub():
    """Minimal stand-in for the Gateway /api/browser surface (real HTTP)."""
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: N802
            pass

        def _json(self, payload: dict, status: int = 200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/api/browser/transport"):
                self._json({"transport": gateway_stub_transport.get("value", "webview2")})
                return
            if self.path.startswith("/api/browser/tabs"):
                self._json(
                    {
                        "tabs": [
                            {
                                "tabId": "primary",
                                "url": "https://example.com/",
                                "title": "Example Domain",
                                "viewport": {"width": 1280, "height": 720},
                                "active": True,
                            }
                        ],
                        "activeTabId": "primary",
                    }
                )
                return
            self._json({"detail": "not found"}, 404)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            received.append(payload)
            command = payload.get("command") or {}
            if command.get("method") == "navigate":
                self._json({"ok": True, "state": {"url": command.get("url"), "title": "Example Domain"}})
                return
            if command.get("method") == "getState":
                self._json({"ok": True, "state": {"url": "https://example.com/", "title": "Example Domain"}})
                return
            if command.get("method") == "viewportSet":
                self._json({"ok": True})
                return
            self._json({"ok": False, "error": {"code": "unknown", "message": "no such command"}}, 200)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], received
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def kernel(gateway_stub):
    """node-repl-host kernel with the bridge setup pre-verified."""
    port, _received = gateway_stub
    import os

    os.environ["EVOFLOW_GATEWAY_PORT"] = str(port)
    from evoflow.plugins.node_repl import call_node_repl_js

    return call_node_repl_js


def test_bridge_symbol_registered(kernel) -> None:
    out = kernel('typeof Symbol.for("zcode.node-repl.browser-control-bridge")')
    assert "symbol" in out


def test_bridge_list_hits_gateway(kernel) -> None:
    out = kernel(
        'globalThis[Symbol.for("zcode.node-repl.browser-control-bridge")].list()'
        ".then((r) => JSON.stringify(r))"
    )
    body = parse_kernel_json(out)
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["id"] == "evoflow-webview"
    assert body[0]["type"] == "iab"
    assert body[0]["metadata"]["url"] == "https://example.com/"


def test_bridge_execute_navigate(kernel, gateway_stub) -> None:
    _port, received = gateway_stub
    out = kernel(
        'globalThis[Symbol.for("zcode.node-repl.browser-control-bridge")]'
        '.execute("evoflow-webview", 1, { method: "navigate", url: "https://example.com/" })'
        ".then((r) => JSON.stringify(r))"
    )
    body = json.loads(out.strip().lstrip("=> \n"))
    assert body["ok"] is True
    assert body["state"]["url"] == "https://example.com/"
    assert received[-1]["command"]["method"] == "navigate"


def test_bridge_maps_browser_viewport_set(kernel, gateway_stub) -> None:
    _port, received = gateway_stub
    out = kernel(
        'globalThis[Symbol.for("zcode.node-repl.browser-control-bridge")]'
        '.execute("evoflow-webview", 1, { method: "browserViewportSet", width: 800, height: 600 })'
        ".then((r) => JSON.stringify(r))"
    )
    body = json.loads(out.strip().lstrip("=> \n"))
    assert body["ok"] is True
    assert received[-1]["command"]["method"] == "viewportSet"
    assert received[-1]["command"]["width"] == 800


def test_bridge_refuses_edge_fallback(kernel) -> None:
    # 用户要求：只驱动客户端内置浏览器面板（webview2）；Edge 回退必须如实拒绝。
    gateway_stub_transport["value"] = "edge"
    try:
        with pytest.raises(Exception, match="WebView2"):
            kernel(
                'globalThis[Symbol.for("zcode.node-repl.browser-control-bridge")]'
                '.execute("evoflow-webview", 1, { method: "navigate", url: "https://x.test/" })'
            )
    finally:
        gateway_stub_transport["value"] = "webview2"


def test_bridge_unmapped_command_structured_error(kernel) -> None:
    out = kernel(
        'globalThis[Symbol.for("zcode.node-repl.browser-control-bridge")]'
        '.execute("evoflow-webview", 1, { method: "recordingStart", options: {} })'
        ".then((r) => JSON.stringify(r))"
    )
    body = json.loads(out.strip().lstrip("=> \n"))
    assert body["ok"] is False
    assert "recordingStart" in body["error"]["message"]

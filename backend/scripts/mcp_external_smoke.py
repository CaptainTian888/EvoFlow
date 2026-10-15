"""External smoke test for a running EvoFlow MCP Streamable-HTTP endpoint.

This script intentionally uses real HTTP and a real bearer token. It does not
construct the FastAPI app, replace dependencies, or mock the MCP registry.

Usage (PowerShell):
    $env:EVOFLOW_MCP_BASE_URL = "http://127.0.0.1:8000"
    $env:EVOFLOW_MCP_TOKEN = "<token>"
    python scripts/mcp_external_smoke.py

Optional read-only tool call:
    $env:EVOFLOW_MCP_TOOL = "<tool name from tools/list>"
    $env:EVOFLOW_MCP_ARGUMENTS_JSON = "{}"

The selected tool must be safe to call in the target environment. The script
never guesses or invokes a tool by default.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx


DEFAULT_PROTOCOL_VERSION = "2024-11-05"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _rpc(client: httpx.Client, url: str, token: str, request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    response = client.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        json=body,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"{method}: expected JSON object, got {type(payload).__name__}")
    if "error" in payload:
        raise AssertionError(f"{method}: JSON-RPC error: {json.dumps(payload['error'], ensure_ascii=False)}")
    if payload.get("id") != request_id:
        raise AssertionError(f"{method}: response id mismatch: {payload.get('id')!r}")
    return payload


def main() -> int:
    base_url = _env("EVOFLOW_MCP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    token = _env("EVOFLOW_MCP_TOKEN")
    tool_name = _env("EVOFLOW_MCP_TOOL")
    arguments_raw = _env("EVOFLOW_MCP_ARGUMENTS_JSON", "{}")
    if not token:
        print("FAIL: EVOFLOW_MCP_TOKEN is required", file=sys.stderr)
        return 2
    try:
        arguments = json.loads(arguments_raw)
    except json.JSONDecodeError as exc:
        print(f"FAIL: EVOFLOW_MCP_ARGUMENTS_JSON is invalid: {exc}", file=sys.stderr)
        return 2
    if not isinstance(arguments, dict):
        print("FAIL: EVOFLOW_MCP_ARGUMENTS_JSON must be a JSON object", file=sys.stderr)
        return 2

    url = f"{base_url}/mcp"
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=30.0) as client:
            initialize = _rpc(
                client,
                url,
                token,
                1,
                "initialize",
                {
                    "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "evoflow-external-smoke", "version": "1.0"},
                },
            )
            init_result = initialize.get("result") or {}
            if "serverInfo" not in init_result or "capabilities" not in init_result:
                raise AssertionError("initialize: missing serverInfo or capabilities")
            print(f"PASS initialize: {init_result.get('serverInfo')}")

            tools_response = _rpc(client, url, token, 2, "tools/list", {})
            tools = (tools_response.get("result") or {}).get("tools")
            if not isinstance(tools, list):
                raise AssertionError("tools/list: result.tools is not a list")
            names = [item.get("name") for item in tools if isinstance(item, dict)]
            print(f"PASS tools/list: {len(tools)} tool(s)")
            if names:
                print("TOOLS:")
                for name in names:
                    print(f"  - {name}")

            if tool_name:
                if tool_name not in names:
                    raise AssertionError(f"tools/call: requested tool is not listed: {tool_name}")
                call_response = _rpc(
                    client,
                    url,
                    token,
                    3,
                    "tools/call",
                    {"name": tool_name, "arguments": arguments},
                )
                result = call_response.get("result") or {}
                if result.get("isError"):
                    raise AssertionError(f"tools/call: tool returned isError=true: {result}")
                print(f"PASS tools/call: {tool_name}")

            unauthenticated = client.post(
                url,
                headers={"Accept": "application/json"},
                json={"jsonrpc": "2.0", "id": 99, "method": "initialize", "params": {}},
            )
            if unauthenticated.status_code != 401:
                raise AssertionError(
                    f"auth: expected 401 without token, got {unauthenticated.status_code}"
                )
            print("PASS auth: missing token rejected with 401")
    except (httpx.HTTPError, AssertionError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"ALL MCP EXTERNAL SMOKE CHECKS PASSED ({elapsed_ms:.0f} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

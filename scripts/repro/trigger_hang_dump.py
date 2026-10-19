#!/usr/bin/env python
"""Trigger a Gateway hang dump on demand (for the "流式对话期间其他接口卡死" repro).

Usage (from PowerShell, after gateway is running on default port 8070):

    cd D:\\dev\\github\\EvoFlow\\backend
    $env:PYTHONPATH = '.'
    python ..\\scripts\\repro\\trigger_hang_dump.py
        # Or to inject latency on /api/chat/sessions:
        # 1. start the gateway with EVOFLOW_OBS_GATEWAY_BODY_SAMPLES=1
        # 2. open a long stream:  curl -N http://localhost:8070/api/.../runs/stream
        # 3. immediately run:  curl http://localhost:8070/api/chat/sessions
        #    → if it takes >5s you should see hang-diagnostics/{reason}.json

What this script does:
    * Sends N concurrent GETs to /api/chat/sessions under a 30s deadline
    * Reports each one's status / latency
    * Prints the most recent hang-diagnostics JSON paths so you can `cat` them
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib import request, error

DEFAULT_GATEWAY = os.environ.get("EVOFLOW_GATEWAY_URL", "http://127.0.0.1:8070")
DEFAULT_LOGS = Path(os.environ.get("EVOFLOW_LOGS_DIR") or Path.home() / ".evoflow-dev" / "logs")


def hit(path: str, timeout: float = 8.0) -> tuple[int, float, str]:
    url = DEFAULT_GATEWAY.rstrip("/") + path
    started = datetime.now().timestamp()
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(256).decode("utf-8", errors="replace")
            return resp.status, (datetime.now().timestamp() - started) * 1000, body[:120]
    except error.HTTPError as e:
        return e.code, (datetime.now().timestamp() - started) * 1000, str(e)
    except Exception as e:  # noqa: BLE001 - want to know everything
        return 0, (datetime.now().timestamp() - started) * 1000, f"{type(e).__name__}: {e}"


def recent_dumps(limit: int = 6) -> list[Path]:
    dump_dir = DEFAULT_LOGS / "debug" / "hang-diagnostics"
    if not dump_dir.is_dir():
        return []
    files = sorted(dump_dir.glob("gateway-hang-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="/api/chat/sessions")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    print(f"[{datetime.now().isoformat(timespec='seconds')}] shooting {args.count} GETs at {args.path}")
    with ThreadPoolExecutor(max_workers=args.count) as pool:
        futures = [pool.submit(hit, args.path, args.timeout) for _ in range(args.count)]
        for fut in as_completed(futures):
            status, ms, snippet = fut.result()
            print(f"  status={status:>3}  {ms:7.1f}ms  body={snippet[:80]}")

    print("\n=== recent hang-diagnostics dumps (newest first) ===")
    for p in recent_dumps():
        print(f"  {p}  ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Print full stream trace logs for a thread.

Usage:
    python -m evoflow.debug.analyze_stream_trace <thread_id>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evoflow.debug.stream_trace import _stream_trace_root, _normalize_thread_id


def print_full_trace(thread_id: str) -> None:
    """Print complete vendor and gateway stream logs for a thread."""
    seg = _normalize_thread_id(thread_id)
    root = _stream_trace_root() / seg
    vendor_file = root / "vendor_stream.jsonl"
    gateway_file = root / "gateway_stream.jsonl"
    
    # Print header
    print(f"\n{'='*80}")
    print(f"STREAM TRACE LOG: {thread_id}")
    print(f"{'='*80}")
    
    # Print vendor stream
    print(f"\n{'='*80}")
    print(f"VENDOR STREAM (Raw LLM Response): {vendor_file}")
    print(f"{'='*80}")
    if vendor_file.exists():
        with open(vendor_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                # Print comment lines as-is (headers)
                if line.startswith("#"):
                    print(line)
                else:
                    try:
                        record = json.loads(line)
                        # Pretty print the JSON
                        print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
                    except json.JSONDecodeError:
                        print(line)
    else:
        print("(file not found)")
    
    # Print gateway stream
    print(f"\n{'='*80}")
    print(f"GATEWAY STREAM (Processed SSE Output): {gateway_file}")
    print(f"{'='*80}")
    if gateway_file.exists():
        with open(gateway_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    print(line)
                else:
                    try:
                        record = json.loads(line)
                        print(json.dumps(record, ensure_ascii=False, indent=2, default=str))
                    except json.JSONDecodeError:
                        print(line)
    else:
        print("(file not found)")
    
    print(f"\n{'='*80}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m evoflow.debug.analyze_stream_trace <thread_id>")
        print()
        print("Available traces:")
        from evoflow.debug.stream_trace import list_trace_threads
        threads = list_trace_threads()
        if threads:
            for t in threads:
                print(f"  - {t}")
        else:
            print("  (none)")
        sys.exit(1)
    
    thread_id = sys.argv[1]
    print_full_trace(thread_id)


if __name__ == "__main__":
    main()

"""Debug helpers (e.g. thread-scoped file logs)."""

from evoflow.debug.analyze_stream_trace import print_full_trace
from evoflow.debug.task_lifecycle_trace import write_task_lifecycle_trace
from evoflow.debug.thread_scoped_file_log import (
    append_jsonl_thread_scoped,
    append_text_block_thread_scoped,
    jsonl_row_with_thread_id,
    normalize_thread_dir_segment,
    thread_log_paths,
)
from evoflow.debug.stream_trace import (
    StreamTrace,
    get_trace_paths,
    list_trace_threads,
    stream_trace,
)

__all__ = [
    "append_jsonl_thread_scoped",
    "append_text_block_thread_scoped",
    "jsonl_row_with_thread_id",
    "normalize_thread_dir_segment",
    "thread_log_paths",
    "write_task_lifecycle_trace",
    # Stream trace
    "StreamTrace",
    "get_trace_paths",
    "list_trace_threads",
    "stream_trace",
    # Print full trace
    "print_full_trace",
]

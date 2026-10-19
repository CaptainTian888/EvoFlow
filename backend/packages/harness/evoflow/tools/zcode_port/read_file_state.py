"""Track files the Read tool has shown the model (ZCode readFileState, mtime only)."""

from __future__ import annotations

import threading
from pathlib import Path

_LOCK = threading.Lock()
_MTIME: dict[str, float] = {}
_MAX_HINT_PATHS = 5


def note_read(path: str) -> None:
    raw = str(path or "").strip()
    if not raw:
        return
    file_path = Path(raw)
    try:
        resolved = str(file_path.resolve())
        mtime = file_path.stat().st_mtime
    except OSError:
        return
    with _LOCK:
        _MTIME[resolved] = mtime


def stale_read_hint() -> str:
    """Paths whose mtime moved since Read. Empty when nothing changed."""
    with _LOCK:
        snapshot = list(_MTIME.items())
    changed: list[str] = []
    for path, seen in snapshot:
        try:
            current = Path(path).stat().st_mtime
        except OSError:
            continue
        if abs(current - seen) > 1e-6:
            changed.append(path)
    if not changed:
        return ""
    shown = changed[:_MAX_HINT_PATHS]
    extra = len(changed) - len(shown)
    more = f"\n(+{extra} more)" if extra else ""
    body = "\n".join(shown)
    return (
        "<system-reminder>Files you previously read changed on disk. "
        "Re-read them with the Read tool before editing:\n"
        f"{body}{more}</system-reminder>"
    )

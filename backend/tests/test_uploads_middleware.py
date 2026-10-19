from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from evoflow.agents.middlewares.uploads_middleware import UploadsMiddleware


class _Paths:
    def __init__(self, uploads_dir: Path):
        self._uploads_dir = uploads_dir

    def sandbox_uploads_dir(self, _thread_id: str) -> Path:
        return self._uploads_dir


def test_upload_middleware_injects_extracted_document_text(tmp_path: Path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    (uploads_dir / "report.pdf").write_bytes(b"pdf")
    monkeypatch.setattr("evoflow.knowledge.parser.parse_file", lambda _path: "Quarterly revenue: 42")

    middleware = UploadsMiddleware()
    middleware._paths = _Paths(uploads_dir)
    state = {
        "messages": [
            HumanMessage(
                content="Summarize this",
                additional_kwargs={
                    "files": [{"filename": "report.pdf", "size": 3, "path": "/mnt/user-data/uploads/report.pdf"}]
                },
            )
        ]
    }
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})

    result = middleware.before_model(state, runtime)

    assert "Quarterly revenue: 42" in result["messages"][0].content
    assert "Content extraction failed" not in result["messages"][0].content


def test_upload_middleware_does_not_parse_image_attachments(tmp_path: Path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    (uploads_dir / "photo.png").write_bytes(b"png")
    monkeypatch.setattr(
        "evoflow.knowledge.parser.parse_file",
        lambda _path: (_ for _ in ()).throw(AssertionError("image must not use document parser")),
    )

    middleware = UploadsMiddleware()
    middleware._paths = _Paths(uploads_dir)
    state = {
        "messages": [
            HumanMessage(
                content="What is in this image?",
                additional_kwargs={
                    "files": [{"filename": "photo.png", "size": 3, "path": "/mnt/user-data/uploads/photo.png"}]
                },
            )
        ]
    }
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})

    result = middleware.before_model(state, runtime)

    assert "Image attached" in result["messages"][0].content

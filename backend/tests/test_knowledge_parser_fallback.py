from __future__ import annotations

from pathlib import Path

from evoflow.knowledge import parser


def test_pdf_parser_falls_back_when_markitdown_fails(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"placeholder")

    class FakePage:
        def extract_text(self):
            return "PDF fallback text"

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(parser, "_convert_with_markitdown", parser._convert_with_markitdown)
    monkeypatch.setitem(__import__("sys").modules, "pdfplumber", type("PdfModule", (), {"open": lambda _path: FakePdf()}))

    class BrokenMarkItDown:
        def convert(self, _path):
            raise RuntimeError("converter unavailable")

    monkeypatch.setitem(__import__("sys").modules, "markitdown", type("MarkModule", (), {"MarkItDown": BrokenMarkItDown}))

    assert parser._convert_with_markitdown(pdf) == "PDF fallback text"

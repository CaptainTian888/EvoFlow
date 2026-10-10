"""Document parser for the evoflow knowledge base.

Converts source files (PDF, DOCX, PPTX, XLSX, TXT, MD) to plain text using
``markitdown`` (already a dependency in ``pyproject.toml``). For ``.txt`` /
``.md`` files, content is read directly without conversion.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions handled by markitdown (binary / rich formats)
_MARKITDOWN_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}

# Extensions read directly as UTF-8 text
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm", ".log", ".py", ".js", ".ts", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".yaml", ".yml", ".toml", ".ini", ".cfg"}


def parse_file(file_path: str | Path) -> str:
    """Parse a document file into plain text.

    Uses ``markitdown`` for binary/rich formats (PDF, DOCX, PPTX, XLSX).
    Reads ``.txt`` / ``.md`` / source code files directly as UTF-8.

    Args:
        file_path: Path to the source file.

    Returns:
        The extracted plain text content.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is not supported.
        RuntimeError: If markitdown conversion fails.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    ext = p.suffix.lower()

    # Direct text read
    if ext in _TEXT_EXTENSIONS:
        return p.read_text(encoding="utf-8", errors="replace")

    # markitdown conversion
    if ext in _MARKITDOWN_EXTENSIONS:
        return _convert_with_markitdown(p)

    # Try markitdown for unknown extensions as a last resort
    logger.warning("Unknown extension '%s', attempting markitdown conversion", ext)
    return _convert_with_markitdown(p)


def _convert_with_markitdown(p: Path) -> str:
    """Convert a file to text, with lightweight fallbacks for common formats."""
    try:
        from markitdown import MarkItDown

        result = MarkItDown().convert(str(p))
        text = result.text_content or ""
        if text.strip():
            return text
        logger.warning("markitdown returned empty content for %s; trying fallback", p.name)
    except Exception as exc:
        logger.warning("markitdown failed for %s: %s; trying fallback", p.name, exc)

    try:
        if p.suffix.lower() == ".pdf":
            import pdfplumber

            with pdfplumber.open(str(p)) as pdf:
                return "\n\n".join((page.extract_text() or "") for page in pdf.pages).strip()
        if p.suffix.lower() in {".docx", ".xlsx"}:
            return _convert_office_fallback(p)
    except ImportError as exc:
        raise RuntimeError(f"无法解析 {p.name}：缺少文档解析依赖（{exc.name}）") from exc
    except Exception as exc:
        raise RuntimeError(f"无法解析 {p.name}：{exc}") from exc

    raise RuntimeError(f"无法解析 {p.name}：MarkItDown 未提取到正文")


def _convert_office_fallback(p: Path) -> str:
    """Extract basic text when optional MarkItDown converters are unavailable."""
    if p.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        book = load_workbook(p, read_only=True, data_only=True)
        try:
            rows = []
            for sheet in book.worksheets:
                rows.append(f"## {sheet.title}")
                rows.extend(" | ".join("" if value is None else str(value) for value in row) for row in sheet.iter_rows(values_only=True))
            return "\n".join(rows).strip()
        finally:
            book.close()

    from zipfile import ZipFile
    from xml.etree import ElementTree

    with ZipFile(p) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t")).strip()


def supported_extensions() -> set[str]:
    """Return the set of all supported file extensions."""
    return _MARKITDOWN_EXTENSIONS | _TEXT_EXTENSIONS

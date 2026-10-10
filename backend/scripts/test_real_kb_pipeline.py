"""Real end-to-end owned knowledge-base test against a running EvoFlow API.

This intentionally does not mock HTTP, parsers, embeddings, SQLite, or jobs.
It creates real PDF/DOCX/XLSX/MD/TXT files, uploads them through port 8070,
waits for the worker, checks retrieval modes, reindexing, and deletion isolation.

Run from backend:
    python scripts/test_real_kb_pipeline.py

The test creates one temporary KB and deletes it in finally. Set
EVOFLOW_KEEP_REAL_KB=1 to keep the KB and fixture files for inspection.
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import openpyxl
import requests

BASE_URL = os.environ.get("EVOFLOW_URL", "http://127.0.0.1:8070").rstrip("/")
TIMEOUT = float(os.environ.get("EVOFLOW_HTTP_TIMEOUT", "30"))
JOB_TIMEOUT = float(os.environ.get("EVOFLOW_JOB_TIMEOUT", "240"))
KEEP = os.environ.get("EVOFLOW_KEEP_REAL_KB") == "1"

CASES = {
    "pdf": ("real_case_pdf.pdf", "PDF_REAL_CASE_ALPHA", "真实 PDF 文档的表格和正文。"),
    "docx": ("real_case_docx.docx", "DOCX_REAL_CASE_BRAVO", "真实 DOCX 标题、段落和表格。"),
    "xlsx": ("real_case_xlsx.xlsx", "XLSX_REAL_CASE_CHARLIE", "真实 XLSX 工作表中的业务数据。"),
    "md": ("real_case_markdown.md", "MARKDOWN_REAL_CASE_DELTA", "真实 Markdown 的结构化内容。"),
    "txt": ("real_case_text.txt", "TXT_REAL_CASE_ECHO", "真实 TXT 纯文本内容。"),
}


def make_pdf(text: str) -> bytes:
    """Build a small valid PDF with one text page, without a parser mock."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


def make_docx(marker: str) -> bytes:
    """Build a real minimal DOCX ZIP with heading, paragraph, and table."""
    content_types = """<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
    document = f"""<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>{marker}</w:t></w:r></w:p><w:p><w:r><w:t>DOCX paragraph with searchable real content.</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>DOCX_TABLE_CELL</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:sectPr/></w:body></w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buf.getvalue()


def make_xlsx(path: Path, marker: str) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Real Data"
    sheet.append(["case", "value", "description"])
    sheet.append([marker, 42, "XLSX_TABLE_VALUE"])
    book.create_sheet("Second Sheet").append(["XLSX_SECOND_SHEET", "preserved"])
    book.save(path)


def request(method: str, path: str, **kwargs: Any) -> requests.Response:
    response = requests.request(method, BASE_URL + path, timeout=TIMEOUT, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:1000]}")
    return response


def json_response(response: requests.Response) -> dict[str, Any]:
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"expected object response, got {type(value).__name__}")
    return value


def upload(kb_id: str, path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return json_response(request("POST", f"/api/knowledge/owned/bases/{kb_id}/documents", files={"file": (path.name, handle)}))


def wait_job(job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + JOB_TIMEOUT
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = json_response(request("GET", f"/api/knowledge/owned/jobs/{job_id}"))
        status = str(last.get("status") or last.get("state") or "").lower()
        if status in {"done", "completed", "complete", "success", "succeeded", "failed", "error"}:
            if status not in {"done", "completed", "complete", "success", "succeeded"}:
                raise RuntimeError(f"job {job_id} failed: {json.dumps(last, ensure_ascii=False)}")
            return last
        time.sleep(1)
    raise TimeoutError(f"job {job_id} did not finish: {json.dumps(last, ensure_ascii=False)}")


def search(kb_id: str, query: str, mode: str) -> dict[str, Any]:
    return json_response(request("POST", f"/api/knowledge/owned/bases/{kb_id}/search", json={"query": query, "mode": mode, "topK": 10}))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def searchable(text: str) -> str:
    """Normalize parser markdown escaping for content assertions."""
    return str(text or "").replace(r"\_", "_").casefold()


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="evoflow-real-kb-"))
    kb_id = ""
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, condition, detail))
        assert_true(condition, f"{name}: {detail}")

    try:
        request("GET", "/openapi.json")
        check("8070 API reachable", True)

        (root / CASES["pdf"][0]).write_bytes(make_pdf(CASES["pdf"][1]))
        (root / CASES["docx"][0]).write_bytes(make_docx(CASES["docx"][1]))
        make_xlsx(root / CASES["xlsx"][0], CASES["xlsx"][1])
        (root / CASES["md"][0]).write_text(f"# {CASES['md'][1]}\n\n{CASES['md'][2]}\n", encoding="utf-8")
        (root / CASES["txt"][0]).write_text(f"{CASES['txt'][1]}\n{CASES['txt'][2]}\n", encoding="utf-8")
        check("real fixture files created", all(path.stat().st_size > 30 for path in root.iterdir()), str(root))

        base = json_response(request("POST", "/api/knowledge/owned/bases", json={
            "name": "REAL_CASE_TEST_KB",
            "description": "temporary real file integration test",
            "embeddingModelRef": "bge-small-zh",
            "summaryEnabled": False,
            "chunkSize": 256,
            "chunkOverlap": 32,
        }))
        kb_id = str(base.get("id") or "")
        check("temporary KB created", bool(kb_id), json.dumps(base, ensure_ascii=False)[:300])

        docs: dict[str, dict[str, Any]] = {}
        for kind, (filename, marker, _description) in CASES.items():
            doc = upload(kb_id, root / filename)
            docs[kind] = doc
            job = doc.get("job") or {}
            job_id = str(job.get("id") or doc.get("jobId") or "")
            check(f"{kind} upload accepted", bool(doc.get("id")) and bool(job_id), json.dumps(doc, ensure_ascii=False)[:300])
            wait_job(job_id)
            current = json_response(request("GET", f"/api/knowledge/owned/documents/{doc['id']}"))
            check(f"{kind} parse completed", current.get("parseStatus") == "completed" and int(current.get("chunkCount") or 0) > 0, json.dumps(current, ensure_ascii=False)[:500])

        for kind, (_filename, marker, _description) in CASES.items():
            result = search(kb_id, marker, "keyword")
            items = result.get("items") or []
            check(f"{kind} keyword retrieval", any(searchable(marker) in searchable(item.get("content") or "") for item in items), json.dumps(result, ensure_ascii=False)[:700])

        semantic = search(kb_id, "business information stored in a spreadsheet", "semantic")
        check("semantic retrieval returns real indexed item", bool(semantic.get("items")), json.dumps(semantic, ensure_ascii=False)[:700])
        hybrid = search(kb_id, CASES["docx"][1], "hybrid")
        check("hybrid retrieval returns real indexed item", bool(hybrid.get("items")), json.dumps(hybrid, ensure_ascii=False)[:700])
        check("hybrid result has source metadata", all(item.get("chunkId") and item.get("docId") for item in hybrid.get("items") or []), json.dumps(hybrid, ensure_ascii=False)[:500])

        reindex = json_response(request("POST", f"/api/knowledge/owned/bases/{kb_id}/reindex", json={}))
        reindex_jobs = reindex.get("jobs") or reindex.get("items") or []
        check("reindex queued", bool(reindex_jobs) or bool(reindex.get("queued")) or bool(reindex.get("reindexQueued")), json.dumps(reindex, ensure_ascii=False)[:500])
        for job in reindex_jobs:
            if isinstance(job, dict) and job.get("id"):
                wait_job(str(job["id"]))
        check("post-reindex keyword retrieval", bool(search(kb_id, CASES["pdf"][1], "keyword").get("items")))

        delete_id = str(docs["txt"]["id"])
        request("DELETE", f"/api/knowledge/owned/documents/{delete_id}")
        deleted = search(kb_id, CASES["txt"][1], "keyword")
        check("deleted document excluded from retrieval", not any(item.get("docId") == delete_id for item in deleted.get("items") or []), json.dumps(deleted, ensure_ascii=False)[:600])

    except Exception as exc:
        checks.append(("unexpected test failure", False, repr(exc)))
        print(json.dumps({"error": repr(exc), "fixtureDir": str(root), "kbId": kb_id}, ensure_ascii=False, indent=2))
        return 1
    finally:
        if kb_id and not KEEP:
            try:
                request("DELETE", f"/api/knowledge/owned/bases/{kb_id}")
            except Exception as exc:
                checks.append(("cleanup temporary KB", False, repr(exc)))
        elif KEEP:
            print(f"KEEP enabled: fixtureDir={root} kbId={kb_id}")
        elif root.exists():
            for child in root.iterdir():
                child.unlink(missing_ok=True)
            root.rmdir()

    print("\n" + "=" * 78)
    print("REAL KNOWLEDGE BASE END-TO-END TEST")
    print("=" * 78)
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" -> {detail}" if detail and not ok else ""))
    passed = sum(ok for _, ok, _ in checks)
    print(f"{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())

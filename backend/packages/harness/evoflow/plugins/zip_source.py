"""Zip plugin source resolution (port of ZCode ``zip-source.ts``).

Downloads a plugin zip over HTTPS (loopback HTTP allowed for tests), verifies
the mandatory sha256 pin, extracts it with the same safety guards (entry count,
per-file and total size caps, traversal/symlink/encryption rejection), and
resolves the plugin root with ZCode's stripRoot/subdir semantics:

1. explicit ``path`` subdirectory wins;
2. plugin manifest at the extract root → root itself;
3. exactly one top-level directory and ``stripRoot is not False`` → that dir;
4. otherwise the extract root.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from .sources import PluginSourceError, ResolvedSourceRoot

ZIP_DOWNLOAD_MAX_BYTES = 200 * 1024 * 1024
ZIP_EXTRACT_MAX_BYTES = 500 * 1024 * 1024
ZIP_MAX_ENTRIES = 20_000
ZIP_MAX_SINGLE_FILE_BYTES = 50 * 1024 * 1024
ZIP_DOWNLOAD_TIMEOUT_SEC = 180

SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")

MANIFEST_RELATIVE_PATHS = (
    ".zcode-plugin/plugin.json",
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
)

_DENIED_HEADERS = {"authorization", "cookie", "proxy-authorization", "set-cookie"}


def is_zip_plugin_url_source(source: Any) -> bool:
    """ZCode ``isZipPluginUrlSource``: ``{source:"url", type:"zip", url, sha256}``."""
    return (
        isinstance(source, dict)
        and source.get("source") == "url"
        and source.get("type") == "zip"
        and isinstance(source.get("url"), str)
        and isinstance(source.get("sha256"), str)
    )


def read_zip_plugin_source_sha256(source: Any) -> str | None:
    if not is_zip_plugin_url_source(source):
        return None
    return str(source["sha256"])


def _validate_download_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme == "https":
        return
    if parts.scheme == "http" and parts.hostname in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        return
    raise PluginSourceError(f"Plugin zip source URL must be HTTPS: {url}")


def _validate_headers(headers: dict[str, str] | None) -> None:
    if not headers:
        return
    for key, value in headers.items():
        if key.lower() in _DENIED_HEADERS:
            raise PluginSourceError(f"Plugin zip source header is not allowed: {key}")
        if not isinstance(value, str):
            raise PluginSourceError(f"Plugin zip source header must be a string: {key}")


def _normalize_zip_relative_path(path: str) -> str:
    if "\0" in path:
        raise PluginSourceError(f"Unsafe plugin zip path: {path}")
    without_trailing = path.rstrip("/")
    if (
        not without_trailing
        or "\\" in path
        or path.startswith("/")
        or re.match(r"^[a-zA-Z]:", path)
    ):
        raise PluginSourceError(f"Unsafe plugin zip path: {path}")
    parts = without_trailing.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PluginSourceError(f"Unsafe plugin zip path: {path}")
    return without_trailing


def _zip_path_within(root: Path, relative: str) -> Path:
    target = (root / Path(*relative.split("/"))).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise PluginSourceError(f"Unsafe plugin zip path: {relative}") from error
    return target


def _has_plugin_manifest(root: Path) -> bool:
    return any((root / relative).is_file() for relative in MANIFEST_RELATIVE_PATHS)


def _download_zip(url: str, headers: dict[str, str] | None) -> bytes:
    try:
        with httpx.Client(
            follow_redirects=True, timeout=ZIP_DOWNLOAD_TIMEOUT_SEC
        ) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError as error:
        raise PluginSourceError(f"Failed to download plugin zip {url}: {error}") from error
    if response.status_code < 200 or response.status_code >= 300:
        raise PluginSourceError(
            f"Failed to download plugin zip: {response.status_code} {url}"
        )
    if len(response.content) > ZIP_DOWNLOAD_MAX_BYTES:
        raise PluginSourceError(
            f"Plugin zip download exceeds size limit: {len(response.content)}/{ZIP_DOWNLOAD_MAX_BYTES}"
        )
    return response.content


def _extract_zip(archive_path: Path, extract_root: Path) -> set[str]:
    extract_root.mkdir(parents=True, exist_ok=True)
    top_level: set[str] = set()
    entry_count = 0
    extracted_bytes = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            for info in infos:
                entry_count += 1
                if entry_count > ZIP_MAX_ENTRIES:
                    raise PluginSourceError(
                        f"Plugin zip has too many entries: {entry_count}/{ZIP_MAX_ENTRIES}"
                    )
                if info.flag_bits & 0x1:
                    raise PluginSourceError(
                        f"Encrypted plugin zip entries are not supported: {info.filename}"
                    )
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_type = unix_mode & 0o170000
                if file_type == 0o120000:
                    raise PluginSourceError(
                        f"Plugin zip entry symlinks are not supported: {info.filename}"
                    )
                normalized = _normalize_zip_relative_path(info.filename)
                top_level.add(PurePosixPath(normalized).parts[0])
                target = _zip_path_within(extract_root, normalized)
                if info.is_dir() or normalized.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if info.file_size > ZIP_MAX_SINGLE_FILE_BYTES:
                    raise PluginSourceError(
                        f"Plugin zip entry exceeds single file limit: {info.filename}"
                    )
                data = archive.read(info)
                extracted_bytes += len(data)
                if extracted_bytes > ZIP_EXTRACT_MAX_BYTES:
                    raise PluginSourceError(
                        f"Plugin zip extracted content exceeds limit: {extracted_bytes}/{ZIP_EXTRACT_MAX_BYTES}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    except zipfile.BadZipFile as error:
        raise PluginSourceError(f"Plugin zip archive is invalid: {error}") from error
    return top_level


def _resolve_zip_root(
    extract_root: Path,
    top_level: set[str],
    path: str | None,
    strip_root: bool | None,
) -> Path:
    if path is not None:
        normalized = _normalize_zip_relative_path(path)
        requested = _zip_path_within(extract_root, normalized)
        if not requested.is_dir():
            raise PluginSourceError(f"Plugin zip source subdirectory does not exist: {path}")
        return requested

    if _has_plugin_manifest(extract_root):
        return extract_root

    if strip_root is not False and len(top_level) == 1:
        segment = next(iter(top_level))
        candidate = _zip_path_within(extract_root, segment)
        if candidate.is_dir():
            return candidate

    if not extract_root.is_dir():
        raise PluginSourceError("Plugin zip did not extract a plugin root directory")
    return extract_root


@dataclass
class ZipSourceInput:
    url: str
    sha256: str | None = None
    path: str | None = None
    strip_root: bool | None = None
    headers: dict[str, str] | None = None


def resolve_zip_plugin_source(input: ZipSourceInput) -> ResolvedSourceRoot:
    """Download, verify, extract, and resolve a zip plugin source (ZCode parity)."""
    _validate_download_url(input.url)
    _validate_headers(input.headers)
    if input.path is not None:
        _normalize_zip_relative_path(input.path)
    if input.sha256 is not None and not SHA256_PATTERN.fullmatch(input.sha256.lower()):
        raise PluginSourceError("Plugin zip source sha256 must be a 64 character hex string")

    temp_root = Path(tempfile.mkdtemp(prefix="evoflow-plugin-zip-"))
    try:
        zip_bytes = _download_zip(input.url, input.headers)
        if input.sha256 is not None:
            actual = hashlib.sha256(zip_bytes).hexdigest()
            if actual != input.sha256.lower():
                raise PluginSourceError(
                    f"Plugin zip sha256 mismatch: expected={input.sha256.lower()}, actual={actual}"
                )
        archive_path = temp_root / "source.zip"
        archive_path.write_bytes(zip_bytes)
        extract_root = temp_root / "extract"
        top_level = _extract_zip(archive_path, extract_root)
        plugin_root = _resolve_zip_root(extract_root, top_level, input.path, input.strip_root)

        def cleanup() -> None:
            shutil.rmtree(temp_root, ignore_errors=True)

        return ResolvedSourceRoot(path=plugin_root, cleanup=cleanup)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


__all__ = [
    "ZipSourceInput",
    "is_zip_plugin_url_source",
    "read_zip_plugin_source_sha256",
    "resolve_zip_plugin_source",
]

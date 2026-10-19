"""Zip plugin source tests — real loopback HTTP download + real extraction.

Covers the ZCode ``zip-source.ts`` port end to end: HTTPS/loopback URL policy,
sha256 pinning, strip-root resolution, manifest assertion, and traversal/size
guards. No mocks — the archive is built on disk and served by a real HTTP
server in-process.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from evoflow.plugins.manifest import PluginManifestError, parse_marketplace_manifest
from evoflow.plugins.sources import PluginSourceError
from evoflow.plugins.storage import (
    InstalledPluginsState,
    load_installed_plugins_state,
    resolve_installed_plugin_root,
)
from evoflow.plugins.zip_source import resolve_zip_plugin_source, ZipSourceInput


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


MANIFEST = {"name": "zipped-plugin", "version": "1.2.3", "description": "zip 插件"}
MANIFEST_AT_ROOT = _zip_bytes(
    {
        ".zcode-plugin/plugin.json": json.dumps(MANIFEST).encode(),
        "commands/hello.md": b"---\ndescription: hi\n---\nhello body",
    }
)
MANIFEST_UNDER_DIR = _zip_bytes(
    {
        "zipped-plugin/.zcode-plugin/plugin.json": json.dumps(MANIFEST).encode(),
        "zipped-plugin/commands/hello.md": b"hello",
    }
)


@pytest.fixture(scope="module")
def zip_server() -> tuple[str, dict[str, str]]:
    """Serve the fixture archives over real loopback HTTP; returns (base_url, shas)."""
    serve_dir = Path(__file__).parent / "__zip_serve__"
    serve_dir.mkdir(exist_ok=True)
    payloads = {
        "root.zip": MANIFEST_AT_ROOT,
        "wrapped.zip": MANIFEST_UNDER_DIR,
        "wrapped-nostrip-flag.zip": MANIFEST_UNDER_DIR,
    }
    shas: dict[str, str] = {}
    for name, data in payloads.items():
        (serve_dir / name).write_bytes(data)
        shas[name] = hashlib.sha256(data).hexdigest()

    handler = partial(SimpleHTTPRequestHandler, directory=str(serve_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    yield base_url, shas
    server.shutdown()
    server.server_close()


def _marketplace_entry(files: dict[str, bytes], tmp_path: Path, source: dict):
    """Write a marketplace manifest with a single zip-source plugin entry."""
    market_dir = tmp_path / "zip-market"
    market_dir.mkdir(exist_ok=True)
    (market_dir / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "zip-market",
                "plugins": [{"name": "zipped-plugin", "version": "1.2.3", "source": source}],
            }
        ),
        encoding="utf-8",
    )
    manifest = parse_marketplace_manifest(
        json.loads((market_dir / "marketplace.json").read_text(encoding="utf-8"))
    )
    return manifest, manifest.entry("zipped-plugin")


def test_resolve_zip_at_extract_root(zip_server, tmp_path) -> None:
    base_url, shas = zip_server
    resolved = resolve_zip_plugin_source(
        ZipSourceInput(url=f"{base_url}/root.zip", sha256=shas["root.zip"])
    )
    try:
        assert (resolved.path / ".zcode-plugin" / "plugin.json").is_file()
        assert (resolved.path / "commands" / "hello.md").is_file()
    finally:
        if resolved.cleanup:
            resolved.cleanup()


def test_resolve_zip_strips_single_top_level_dir(zip_server) -> None:
    base_url, shas = zip_server
    resolved = resolve_zip_plugin_source(
        ZipSourceInput(url=f"{base_url}/wrapped.zip", sha256=shas["wrapped.zip"])
    )
    try:
        # Raw zip nests everything under zipped-plugin/; strip-root resolves to
        # the inner dir so the manifest sits directly at the resolved root.
        assert (resolved.path / ".zcode-plugin" / "plugin.json").is_file()
        assert resolved.path.name == "zipped-plugin"
    finally:
        if resolved.cleanup:
            resolved.cleanup()


def test_zip_sha256_mismatch_rejected(zip_server) -> None:
    base_url, _shas = zip_server
    with pytest.raises(PluginSourceError, match="sha256 mismatch"):
        resolve_zip_plugin_source(
            ZipSourceInput(url=f"{base_url}/root.zip", sha256="a" * 64)
        )


def test_zip_non_https_url_rejected() -> None:
    with pytest.raises(PluginSourceError, match="HTTPS"):
        resolve_zip_plugin_source(
            ZipSourceInput(url="http://cdn.example.com/plugin.zip", sha256="a" * 64)
        )


def test_zip_traversal_entry_rejected(tmp_path: Path) -> None:
    from evoflow.plugins.zip_source import _extract_zip, _normalize_zip_relative_path

    evil = _zip_bytes({"../escape.txt": b"nope"})
    archive = tmp_path / "evil.zip"
    archive.write_bytes(evil)
    with pytest.raises(PluginSourceError, match="Unsafe plugin zip path"):
        _normalize_zip_relative_path("../escape.txt")
    with pytest.raises(PluginSourceError, match="Unsafe plugin zip path"):
        _extract_zip(archive, tmp_path / "extract")
    assert not (tmp_path / "escape.txt").exists()


def test_install_zip_plugin_end_to_end(zip_server, tmp_path) -> None:
    from evoflow.plugins.service import PluginManagementService

    base_url, shas = zip_server
    storage_root = tmp_path / "plugins"
    service = PluginManagementService(storage_root=storage_root)
    source = {
        "source": "url",
        "type": "zip",
        "url": f"{base_url}/wrapped.zip",
        "sha256": shas["wrapped.zip"],
    }
    manifest, _entry = _marketplace_entry(dict(source=source), tmp_path, source)
    # Seed the manifest cache + known record directly (real files, no HTTP).
    from evoflow.plugins.storage import (
        save_marketplace_manifest_cache,
        upsert_known_marketplace,
        KnownMarketplaceRecord,
    )

    save_marketplace_manifest_cache(service.storage_root, manifest.raw)
    upsert_known_marketplace(
        service.storage_root,
        KnownMarketplaceRecord(
            id="zip-market",
            source={"source": "settings"},
            name="zip-market",
            addedAt="2026-01-01T00:00:00Z",
            pluginCount=1,
        ),
    )

    result = service.install_plugin("zip-market", "zipped-plugin")
    assert result["dependencyClosure"] == ["zipped-plugin@zip-market"]
    record = result["installedPlugins"][0]
    assert record["version"] == "1.2.3"
    install_root = Path(record["installPath"])
    assert (install_root / ".zcode-plugin" / "plugin.json").is_file()

    state: InstalledPluginsState = load_installed_plugins_state(storage_root)
    assert state.is_enabled("zipped-plugin@zip-market")
    persisted = next(
        r for r in state.plugins if r.id == "zipped-plugin@zip-market"
    )
    assert resolve_installed_plugin_root(storage_root, persisted).is_dir()


def test_zip_manifest_name_mismatch_rejected(zip_server, tmp_path) -> None:
    from evoflow.plugins.service import PluginManagementService

    base_url, shas = zip_server
    storage_root = tmp_path / "plugins2"
    service = PluginManagementService(storage_root=storage_root)
    # Entry claims a different name than the manifest inside the zip.
    source = {
        "source": "url",
        "type": "zip",
        "url": f"{base_url}/wrapped.zip",
        "sha256": shas["wrapped.zip"],
    }
    market_dir = tmp_path / "zip-market2"
    market_dir.mkdir()
    (market_dir / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "zip-market2",
                "plugins": [{"name": "other-name", "version": "1.0.0", "source": source}],
            }
        ),
        encoding="utf-8",
    )
    from evoflow.plugins.storage import (
        KnownMarketplaceRecord,
        save_marketplace_manifest_cache,
        upsert_known_marketplace,
    )

    payload = json.loads((market_dir / "marketplace.json").read_text(encoding="utf-8"))
    save_marketplace_manifest_cache(service.storage_root, payload)
    upsert_known_marketplace(
        service.storage_root,
        KnownMarketplaceRecord(
            id="zip-market2",
            source={"source": "settings"},
            name="zip-market2",
            addedAt="2026-01-01T00:00:00Z",
            pluginCount=1,
        ),
    )
    with pytest.raises(PluginManifestError, match="does not match marketplace entry"):
        service.install_plugin("zip-market2", "other-name")

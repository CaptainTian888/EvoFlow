"""Official marketplace seed uses only the packaged plugin bundle."""

from __future__ import annotations

from pathlib import Path

import pytest

from evoflow.plugins import builtin as builtin_mod
from evoflow.plugins.builtin import (
    SEED_MANIFEST_VERSION,
    build_official_marketplace_manifest,
    seed_official_marketplace,
)


def test_demo_seed_without_packaged_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtin_mod, "discover_bundled_official_cache", lambda: None)

    manifest = build_official_marketplace_manifest()
    names = {p["name"] for p in manifest["plugins"]}
    assert names == {"evoflow-guide", "hello-command", "evoflow-skill-kit"}


def test_bundled_cache_synthesizes_browser_and_computer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "bundle"
    for name, ver in (("browser-use", "0.5.1"), ("computer-use", "0.6.4")):
        root = cache / name / ver
        root.mkdir(parents=True)
        (root / ".evoflow-plugin").mkdir()
        (root / ".evoflow-plugin" / "plugin.json").write_text(
            f'{{"name":"{name}","version":"{ver}"}}',
            encoding="utf-8",
        )

    monkeypatch.setattr(builtin_mod, "discover_bundled_official_cache", lambda: cache)

    manifest = build_official_marketplace_manifest()
    by_name = {p["name"]: p for p in manifest["plugins"]}
    assert by_name["browser-use"]["source"] == "filesystem"
    assert Path(by_name["browser-use"]["cachePath"]).is_dir()
    assert by_name["computer-use"]["source"] == "filesystem"
    assert "evoflow-guide" in by_name


def test_listing_row_without_packaged_files_is_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "bundle"
    cache.mkdir()
    (cache / "marketplace.json").write_text(
        '{"name":"evoflow-plugins-official","plugins":['
        '{"name":"github","version":"0.1.2","source":{"source":"url","type":"zip",'
        '"url":"https://example.invalid/github.zip","sha256":"'
        + ("a" * 64)
        + '"}}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(builtin_mod, "discover_bundled_official_cache", lambda: cache)

    manifest = build_official_marketplace_manifest()
    names = {p["name"] for p in manifest["plugins"]}
    assert "github" not in names
    assert "evoflow-guide" in names


def test_seed_version_bump_rewrites_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(builtin_mod, "discover_bundled_official_cache", lambda: None)
    monkeypatch.setattr(builtin_mod, "_localize_official_icons", lambda *_a, **_k: None)

    storage = tmp_path / "plugins"
    first = seed_official_marketplace(storage)
    assert first.get("__seededVersion") == SEED_MANIFEST_VERSION
    assert any(p["name"] == "hello-command" for p in first["plugins"])

    from evoflow.plugins.storage import load_marketplace_manifest_cached, save_marketplace_manifest_cache

    stale = dict(first)
    stale["__seededVersion"] = 1
    stale["plugins"] = [{"name": "evoflow-guide", "source": "filesystem", "cachePath": str(tmp_path)}]
    save_marketplace_manifest_cache(storage, stale)

    again = seed_official_marketplace(storage)
    assert again.get("__seededVersion") == SEED_MANIFEST_VERSION
    names = {p["name"] for p in again["plugins"]}
    assert "hello-command" in names
    cached = load_marketplace_manifest_cached(storage, "evoflow-plugins-official")
    assert cached is not None
    assert cached.raw.get("__seededVersion") == SEED_MANIFEST_VERSION

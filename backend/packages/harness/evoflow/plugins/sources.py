"""Marketplace and plugin source parsing/resolution (ZCode parity subset).

Supported marketplace sources: ``url`` (direct marketplace.json over HTTP),
``file`` / ``directory`` (local), ``github`` (``owner/repo`` shorthand),
``git`` (arbitrary git URL). ``npm`` / ``hostPattern`` / ``pathPattern`` are
rejected with explicit diagnostics, matching ZCode's unsupported set.

Supported plugin sources: relative string path inside the marketplace,
``directory`` (absolute path), ``github`` / ``git`` / ``git-subdir`` / ``url``
(git), plus the bundled ``filesystem`` / ``sea`` kinds backed by ``cachePath``.
``zip`` URL sources (sha256-pinned, ZCode ``zip-source.ts`` semantics) are supported; ``npm`` / ``pip`` are explicitly unsupported.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .manifest import (
    EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE,
    MarketplaceEntry,
    MarketplaceManifest,
    PluginDiagnostic,
    PluginManifestError,
    find_marketplace_manifest_path,
    find_plugin_manifest_path,
    parse_marketplace_manifest,
    read_marketplace_manifest_from_path,
)

GIT_COMMAND_TIMEOUT_SEC = 120
MARKETPLACE_JSON_TIMEOUT_SEC = 120


class PluginSourceError(Exception):
    """Raised when a marketplace/plugin source cannot be resolved."""


@dataclass
class ResolvedSourceRoot:
    path: Path
    cleanup: Any = None  # optional zero-arg callable removing a temp clone


def parse_marketplace_source_input(source: str) -> dict[str, Any]:
    """Parse a free-form source string into a canonical source dict."""
    trimmed = (source or "").strip()
    if not trimmed:
        raise PluginSourceError("Marketplace source is empty")
    if trimmed.startswith("http://") or trimmed.startswith("https://"):
        if trimmed.endswith(".git") or "/_git/" in trimmed:
            return {"source": "git", "url": trimmed}
        parsed = urlparse(trimmed)
        if parsed.hostname in ("github.com", "www.github.com"):
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                return {
                    "source": "git",
                    "url": trimmed if trimmed.endswith(".git") else f"{trimmed}.git",
                }
        return {"source": "url", "url": trimmed}
    if trimmed.startswith("git@"):
        return {"source": "git", "url": trimmed}
    # Local path (absolute or relative)
    candidate = Path(trimmed).expanduser()
    resolved = candidate if candidate.is_absolute() else (Path.cwd() / candidate)
    try:
        resolved = resolved.resolve()
    except OSError:
        resolved = candidate
    if resolved.exists():
        if resolved.is_file():
            if resolved.suffix.lower() != ".json":
                raise PluginSourceError(f"Marketplace file must be a .json file: {resolved}")
            return {"source": "file", "path": str(resolved)}
        return {"source": "directory", "path": str(resolved)}
    if "/" in trimmed and ":" not in trimmed:
        # GitHub owner/repo shorthand
        return {"source": "github", "repo": trimmed}
    raise PluginSourceError(f"Unsupported marketplace source: {source}")


def fetch_marketplace_json(url: str) -> dict[str, Any]:
    """Fetch a marketplace JSON document over HTTP with a hard size cap."""
    try:
        with httpx.Client(follow_redirects=True, timeout=MARKETPLACE_JSON_TIMEOUT_SEC) as client:
            response = client.get(url)
    except httpx.HTTPError as error:
        raise PluginSourceError(f"Failed to fetch marketplace {url}: {error}") from error
    if response.status_code < 200 or response.status_code >= 300:
        raise PluginSourceError(f"Failed to fetch marketplace: {response.status_code} {url}")
    if len(response.content) > 10 * 1024 * 1024:
        raise PluginSourceError(f"Marketplace JSON exceeds 10MB limit: {url}")
    import json

    try:
        payload = json.loads(response.content.decode("utf-8"))
    except ValueError as error:
        raise PluginSourceError(f"Marketplace JSON is invalid: {url}: {error}") from error
    if not isinstance(payload, dict):
        raise PluginSourceError(f"Marketplace JSON is not an object: {url}")
    return payload


def _run_git(args: list[str]) -> None:
    try:
        from evoflow.utils.subprocess_platform import (
            subprocess_hide_window_kwargs,
            subprocess_text_io_kwargs,
        )

        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT_SEC,
            **subprocess_hide_window_kwargs(),
            **subprocess_text_io_kwargs(),
        )
    except FileNotFoundError as error:
        raise PluginSourceError("Git is not available on this machine") from error
    except subprocess.TimeoutExpired as error:
        raise PluginSourceError(f"Git command timed out: {' '.join(args[:2])}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {result.returncode}"
        raise PluginSourceError(f"Git operation failed: {message}")


def clone_to_temp(url: str, ref: str | None = None, subdir: str | None = None) -> ResolvedSourceRoot:
    workdir = Path(tempfile.mkdtemp(prefix="evoflow-plugin-src-"))
    args = ["clone", "--depth", "1"]
    if ref:
        args += ["--branch", ref]
    args += [url, str(workdir)]
    try:
        _run_git(args)
    except Exception:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)
        raise
    target = workdir
    if subdir:
        target = workdir / subdir
        if not target.is_dir():
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)
            raise PluginSourceError(f"Plugin source subdirectory does not exist: {subdir}")

    def cleanup() -> None:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)

    return ResolvedSourceRoot(path=target, cleanup=cleanup)


def resolve_marketplace_source_root(source: dict[str, Any]) -> tuple[MarketplaceManifest, ResolvedSourceRoot | None]:
    """Load and parse a marketplace manifest from any supported source.

    Returns the parsed manifest and, when the source materialized a temporary
    clone, its cleanup handle (callers must invoke it in ``finally``).
    """
    kind = source.get("source")
    if kind == "file":
        path = Path(str(source.get("path") or "")).expanduser()
        if not path.is_file():
            raise PluginSourceError(f"Marketplace file does not exist: {path}")
        manifest = read_marketplace_manifest_from_path(path)
        root = ResolvedSourceRoot(path=path.parent)
        return manifest, root
    if kind == "directory":
        path = Path(str(source.get("path") or "")).expanduser()
        if not path.is_dir():
            raise PluginSourceError(f"Marketplace directory does not exist: {path}")
        manifest_path = find_marketplace_manifest_path(path)
        if manifest_path is None:
            raise PluginSourceError(f"Marketplace manifest not found in directory: {path}")
        manifest = read_marketplace_manifest_from_path(manifest_path)
        return manifest, ResolvedSourceRoot(path=path)
    if kind == "url":
        payload = fetch_marketplace_json(str(source.get("url") or ""))
        manifest = parse_marketplace_manifest(payload, str(source.get("url")))
        return manifest, None
    if kind in ("github", "git"):
        url = (
            f"https://github.com/{source.get('repo')}.git"
            if kind == "github"
            else str(source.get("url") or "")
        )
        if not url:
            raise PluginSourceError("Git marketplace source requires a url")
        ref = source.get("ref") if isinstance(source.get("ref"), str) else None
        subdir = source.get("path") if isinstance(source.get("path"), str) else None
        resolved = clone_to_temp(url, ref=ref)
        try:
            manifest_path = find_marketplace_manifest_path(resolved.path, subdir)
            if manifest_path is None:
                raise PluginSourceError(f"Marketplace manifest not found in git repo: {url}")
            manifest = read_marketplace_manifest_from_path(manifest_path)
        except Exception:
            if resolved.cleanup:
                resolved.cleanup()
            raise
        return manifest, resolved
    if kind == "settings":
        # Builtin seeded marketplaces carry the manifest inline.
        inline = source.get("manifest")
        if isinstance(inline, dict):
            manifest = parse_marketplace_manifest(inline, "builtin")
            return manifest, None
        raise PluginSourceError("Settings marketplace source requires an inline manifest")
    raise PluginSourceError(f"Unsupported marketplace source: {kind}")


def validate_marketplace_source_only(source: dict[str, Any]) -> list[PluginDiagnostic]:
    """Dry-run validation: load the manifest and check entry shape only."""
    diagnostics: list[PluginDiagnostic] = []
    resolved: ResolvedSourceRoot | None = None
    try:
        manifest, resolved = resolve_marketplace_source_root(source)
    except (PluginSourceError, PluginManifestError) as error:
        diagnostics.append(PluginDiagnostic(code="plugin_marketplace_invalid", message=str(error)))
        return diagnostics
    finally:
        if resolved and resolved.cleanup:
            try:
                resolved.cleanup()
            except Exception:
                pass
    if not manifest.plugins:
        diagnostics.append(
            PluginDiagnostic(
                code="plugin_marketplace_invalid",
                message=f"Marketplace has no plugins: {manifest.name}",
                severity="warning",
            )
        )
    for entry in manifest.plugins:
        from .manifest import validate_plugin_name

        name_error = validate_plugin_name(entry.name)
        if name_error:
            diagnostics.append(
                PluginDiagnostic(
                    code="plugin_marketplace_invalid",
                    message=name_error,
                    pluginId=f"{entry.name}@{manifest.name}",
                )
            )
    return diagnostics


def _resolve_inside(base: Path, relative: str) -> Path | None:
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate


def resolve_plugin_source_root(
    entry: MarketplaceEntry,
    manifest: MarketplaceManifest,
    marketplace_dir: Path | None,
    storage_root: Path,
) -> ResolvedSourceRoot:
    """Resolve the plugin root directory for a marketplace entry.

    Temporary clones carry a ``cleanup`` handle; persistent local directories
    (marketplace dir, cachePath, cache dir) do not.
    """
    source = entry.source
    base_dir = marketplace_dir
    if base_dir is not None and manifest.plugin_root:
        plugin_root_dir = _resolve_inside(base_dir, manifest.plugin_root)
        if plugin_root_dir is not None and plugin_root_dir.is_dir():
            base_dir = plugin_root_dir

    if source == "filesystem" or source == "sea":
        cache_path = entry.cache_path
        if cache_path and Path(cache_path).is_dir():
            return ResolvedSourceRoot(path=Path(cache_path))
        computed = storage_root / "cache" / manifest.name / entry.name / (entry.version or "0.0.0")
        if computed.is_dir():
            return ResolvedSourceRoot(path=computed)
        raise PluginSourceError(f"Bundled plugin cache directory missing: {entry.name}@{manifest.name}")

    if isinstance(source, str):
        if base_dir is None:
            raise PluginSourceError(
                f"Plugin source {source!r} requires a local marketplace directory"
            )
        local = _resolve_inside(base_dir, source.removeprefix("./"))
        if local is not None and local.is_dir():
            return ResolvedSourceRoot(path=local)
        absolute = Path(source).expanduser()
        if absolute.is_dir():
            return ResolvedSourceRoot(path=absolute)
        raise PluginSourceError(f"Unsupported or missing plugin source: {source}")

    if isinstance(source, dict):
        source_kind = source.get("source")
        if source_kind == "directory":
            path = Path(str(source.get("path") or "")).expanduser()
            if path.is_dir():
                return ResolvedSourceRoot(path=path)
            raise PluginSourceError(f"Plugin source directory does not exist: {path}")
        if source_kind == "github":
            url = f"https://github.com/{source.get('repo')}.git"
            return _resolve_repository_source(source, url)
        if source_kind == "git":
            return _resolve_repository_source(source, str(source.get("url") or ""))
        if source_kind == "url":
            url = str(source.get("url") or "")
            source_type = source.get("type")
            if source_type == "zip":
                from .zip_source import ZipSourceInput, resolve_zip_plugin_source

                return resolve_zip_plugin_source(
                    ZipSourceInput(
                        url=url,
                        sha256=source.get("sha256") if isinstance(source.get("sha256"), str) else None,
                        path=source.get("path") if isinstance(source.get("path"), str) else None,
                        strip_root=source.get("stripRoot") if isinstance(source.get("stripRoot"), bool) else None,
                        headers=source.get("headers") if isinstance(source.get("headers"), dict) else None,
                    )
                )
            return _resolve_repository_source(source, url)
        if source_kind == "git-subdir":
            source_with_path = dict(source)
            source_with_path.setdefault("path", source.get("path"))
            url = str(source.get("url") or "")
            if "/" in url and ":" not in url and not url.startswith("git@"):
                url = f"https://github.com/{url}.git"
            return _resolve_repository_source(
                source_with_path,
                url,
                require_path=True,
            )
        if source_kind in ("npm", "pip"):
            raise PluginSourceError(f"Plugin source kind {source_kind!r} is not supported")
        raise PluginSourceError(
            f"Plugin source is invalid or unsupported for {entry.name}@{manifest.name}: "
            f"{source_kind or 'missing kind'}"
        )

    if base_dir is not None:
        local_by_name = base_dir / entry.name
        if local_by_name.is_dir():
            return ResolvedSourceRoot(path=local_by_name)
    raise PluginSourceError(f"Plugin source is not supported for {entry.name}@{manifest.name}")


def _resolve_repository_source(
    source: dict[str, Any], url: str, require_path: bool = False
) -> ResolvedSourceRoot:
    if not url:
        raise PluginSourceError("Repository plugin source requires a url")
    ref = source.get("ref") if isinstance(source.get("ref"), str) else None
    subdir = source.get("path") if isinstance(source.get("path"), str) else None
    if require_path and not subdir:
        raise PluginSourceError("git-subdir plugin source requires a path")
    resolved = clone_to_temp(url, ref=ref, subdir=subdir)
    return resolved


def plugin_manifest_at_root(root: Path):
    from .manifest import read_plugin_manifest_from_root

    return read_plugin_manifest_from_root(root)




__all__ = [
    "EVOFLOW_OFFICIAL_PLUGIN_MARKETPLACE",
    "PluginSourceError",
    "ResolvedSourceRoot",
    "clone_to_temp",
    "fetch_marketplace_json",
    "parse_marketplace_source_input",
    "plugin_manifest_at_root",
    "resolve_marketplace_source_root",
    "resolve_plugin_source_root",
    "validate_marketplace_source_only",
]

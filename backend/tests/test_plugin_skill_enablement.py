"""Scope precedence for same-named skills (user-defined > plugin > system).

Regression for the user-reported ``computer-use`` failure: the plugin was
installed and enabled, but a stale registry row from a same-named custom
skill disabled the name entirely ("exists but is disabled in config").

Rules encoded here:
1. A disabled user-defined skill must not dead-end the name — the enabled
   plugin instance serves (fall-through).
2. An *enabled* user-defined skill outranks the plugin instance (user
   definition is the authority for their own name).
3. A plugin skill outranks a same-named system-seeded (public) skill.
4. With no plugin instance, the registry row keeps its authority (disabled
   custom skill stays disabled).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_skill(root: Path, subdir: str, name: str, body_marker: str) -> Path:
    skill_dir = root / subdir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {body_marker}\n---\n{body_marker}",
        encoding="utf-8",
    )
    return skill_dir


def _setup_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    custom_dir: Path | None,
    public_dir: Path | None,
    plugin_dir: Path | None,
    registry_enabled: bool | None,
) -> None:
    primary = tmp_path / "skills"
    primary.mkdir(parents=True, exist_ok=True)
    if custom_dir is not None:
        _make_skill(primary, "custom", "conflicted", "stale custom body")
    if public_dir is not None:
        _make_skill(primary, "public", "conflicted", "system public body")
    monkeypatch.setenv("EVOFLOW_SKILLS_PATH", str(primary))

    plugin_roots: list[Path] = []
    if plugin_dir is not None:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "SKILL.md").write_text(
            "---\nname: conflicted\ndescription: plugin skill\n---\nplugin skill body",
            encoding="utf-8",
        )
        plugin_roots.append(plugin_dir.parent)
    monkeypatch.setattr(
        "evoflow.plugins.runtime.plugin_skill_roots", lambda storage_root=None: plugin_roots
    )

    from evoflow.persistence import config_repositories as cfg_repo

    registry = {} if registry_enabled is None else {"conflicted": {"enabled": registry_enabled}}
    monkeypatch.setattr(cfg_repo, "list_skill_registry", lambda: registry)
    monkeypatch.setattr(
        "evoflow.persistence.bootstrap.sync_skills_from_filesystem", lambda: None
    )

    from evoflow.skills import loader

    monkeypatch.setattr(loader, "_skills_cache", None)
    monkeypatch.setattr(loader, "_plugin_state_sig", None)


def test_disabled_custom_falls_through_to_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins" / "cache" / "p1" / "skills" / "conflicted"
    _setup_env(
        monkeypatch, tmp_path, custom_dir=Path("custom"), public_dir=None,
        plugin_dir=plugin_dir, registry_enabled=False,
    )
    from evoflow.skills.skill_uri import resolve_skill_uri

    resolved = resolve_skill_uri("skill:conflicted")
    assert resolved is not None, "enabled plugin must serve when the user instance is disabled"
    assert resolved.parent.resolve() == plugin_dir.resolve()


def test_enabled_custom_shadows_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins" / "cache" / "p1" / "skills" / "conflicted"
    _setup_env(
        monkeypatch, tmp_path, custom_dir=Path("custom"), public_dir=None,
        plugin_dir=plugin_dir, registry_enabled=True,
    )
    from evoflow.skills.skill_uri import resolve_skill_uri

    resolved = resolve_skill_uri("skill:conflicted")
    assert resolved is not None
    assert "plugins" not in str(resolved.parent), "user-defined skill must outrank the plugin"


def test_plugin_shadows_system_public_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_dir = tmp_path / "plugins" / "cache" / "p1" / "skills" / "conflicted"
    _setup_env(
        monkeypatch, tmp_path, custom_dir=None, public_dir=Path("public"),
        plugin_dir=plugin_dir, registry_enabled=True,
    )
    from evoflow.skills.skill_uri import resolve_skill_uri

    resolved = resolve_skill_uri("skill:conflicted")
    assert resolved is not None
    assert resolved.parent.resolve() == plugin_dir.resolve()


def test_registry_row_still_disables_without_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_env(
        monkeypatch, tmp_path, custom_dir=Path("custom"), public_dir=None,
        plugin_dir=None, registry_enabled=False,
    )
    from evoflow.skills.skill_uri import format_skill_uri_error

    error = format_skill_uri_error("skill:conflicted/SKILL.md", require_enabled=True)
    assert "disabled" in error

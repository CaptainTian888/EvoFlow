"""Plugin ↔ agent runtime integration tests (skills discovery + turn injection)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evoflow.plugins.runtime import (
    build_plugin_injection_block,
    enabled_plugin_roots,
    plugin_skill_roots,
    plugin_state_signature,
)


@pytest.fixture()
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "plugins"
    monkeypatch.setenv("EVOFLOW_PLUGIN_STORAGE_ROOT", str(root))
    from evoflow.plugins.service import PluginManagementService

    PluginManagementService(storage_root=root).install_plugin(
        "evoflow-plugins-official", "hello-command"
    )
    PluginManagementService(storage_root=root).install_plugin(
        "evoflow-plugins-official", "evoflow-skill-kit"
    )
    return root


def test_enabled_plugin_roots_and_skill_roots(storage_root: Path) -> None:
    roots = enabled_plugin_roots(storage_root)
    root_ids = {plugin_id for plugin_id, _root in roots}
    # Default-seeded official plugins + the two explicitly installed ones.
    assert "hello-command@evoflow-plugins-official" in root_ids
    assert "evoflow-skill-kit@evoflow-plugins-official" in root_ids
    assert "browser-use@evoflow-plugins-official" in root_ids
    skill_roots = plugin_skill_roots(storage_root)
    assert any((root / "greeting" / "SKILL.md").is_file() for root in skill_roots)


def test_plugin_skill_roots_follow_enable_state(storage_root: Path) -> None:
    from evoflow.plugins.service import PluginManagementService

    plugin_id = "evoflow-skill-kit@evoflow-plugins-official"
    before = [root for root in plugin_skill_roots(storage_root) if (root / "greeting").is_dir()]
    assert len(before) == 1
    PluginManagementService(storage_root=storage_root).set_plugin_enabled(plugin_id, False)
    after = [root for root in plugin_skill_roots(storage_root) if (root / "greeting").is_dir()]
    assert after == []
    assert plugin_state_signature(storage_root).endswith(":0")


def test_build_plugin_injection_block_is_metadata_only(storage_root: Path) -> None:
    block = build_plugin_injection_block(
        ["hello-command@evoflow-plugins-official", "evoflow-skill-kit"], storage_root
    )
    assert block.startswith("<plugin_injection>")
    assert '<plugin id="hello-command@evoflow-plugins-official">' in block
    # Commands ship as metadata lines (name + description), not bodies.
    assert '<command name="hello" description="打一声来自 EvoFlow 插件体系的招呼" />' in block
    assert "你好，这是来自 EvoFlow 插件 hello-command 的问候" not in block
    # Skills ship as name/location/description metadata — never SKILL.md bodies.
    assert '<skill name="greeting" location="skill:greeting"' in block
    assert "由插件体系在安装后自动发现" not in block
    assert block.strip().endswith("</plugin_injection>")


def test_invoked_command_body_is_inlined(storage_root: Path) -> None:
    block = build_plugin_injection_block(
        ["hello-command@evoflow-plugins-official", "evoflow-skill-kit"],
        storage_root,
        user_message="/hello 打个招呼",
    )
    assert '<command name="hello" invoked="true">' in block
    assert "你好，这是来自 EvoFlow 插件 hello-command 的问候" in block
    # Skills stay metadata-only even when commands are invoked.
    assert "由插件体系在安装后自动发现" not in block
    # URLs and paths must not count as command invocations.
    block = build_plugin_injection_block(
        ["hello-command"], storage_root, user_message="see https://x/hello and D:\\a\\hello"
    )
    assert "你好，这是来自 EvoFlow 插件 hello-command 的问候" not in block


def test_build_plugin_injection_block_respects_disabled(storage_root: Path) -> None:
    from evoflow.plugins.service import PluginManagementService

    PluginManagementService(storage_root=storage_root).set_plugin_enabled(
        "hello-command@evoflow-plugins-official", False
    )
    block = build_plugin_injection_block(["hello-command"], storage_root)
    assert block == ""
    # Unknown plugins are silently skipped.
    assert build_plugin_injection_block(["nope"], storage_root) == ""
    # Bare-name resolution still works for enabled plugins.
    block = build_plugin_injection_block(["evoflow-skill-kit"], storage_root)
    assert '<skill name="greeting"' in block


def test_plugin_injection_block_budget_drops_overflow(storage_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evoflow.plugins import runtime as plugin_runtime

    hello_root = next(
        root for plugin_id, root in plugin_runtime.enabled_plugin_roots(storage_root)
        if plugin_id.startswith("hello-command")
    )
    kit_root = next(
        root for plugin_id, root in plugin_runtime.enabled_plugin_roots(storage_root)
        if plugin_id.startswith("evoflow-skill-kit")
    )
    _first, first_used = plugin_runtime._render_plugin_section(
        "hello-command@evoflow-plugins-official", hello_root, set()
    )
    monkeypatch.setattr(plugin_runtime, "_PLUGIN_INJECTION_MAX_CHARS", first_used + 10)

    block = build_plugin_injection_block(
        ["hello-command@evoflow-plugins-official", "evoflow-skill-kit"], storage_root
    )
    assert '<plugin id="hello-command@evoflow-plugins-official">' in block
    assert '<plugin id="evoflow-skill-kit@evoflow-plugins-official">' not in block
    assert "truncated" in block
    assert block.strip().endswith("</plugin_injection>")


def test_load_skills_discovers_plugin_skills(storage_root: Path) -> None:
    from evoflow.skills.loader import load_skills
    from evoflow.skills.skill_scope import SkillScope

    skills = load_skills(enabled_only=True)
    greeting = [s for s in skills if s.name == "greeting"]
    assert len(greeting) == 1
    assert greeting[0].enabled is True
    assert greeting[0].scope == SkillScope.EXTERNAL
    assert greeting[0].source_root is not None and "plugins" in str(greeting[0].source_root)
    # skill:<name> URI resolution works for plugin skills.
    from evoflow.skills.skill_uri import resolve_skill_uri

    resolved = resolve_skill_uri("skill:greeting")
    assert resolved is not None and resolved.is_file()


def test_select_skills_for_turn_includes_plugin_skill(storage_root: Path) -> None:
    from evoflow.skills.selection import select_skills_for_turn

    selected = select_skills_for_turn(preferred_skills=["greeting"], user_message="")
    assert [s.name for s in selected] == ["greeting"]

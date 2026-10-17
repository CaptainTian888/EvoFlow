"""Degradation ladder for the <skill_system> catalog (injection_budget §skills).

full descriptions → sentence-capped descriptions → names-only, mirroring
ZCode's metadata-budget fallback: an oversized catalog must never ship
half-cut prose, and every skill stays discoverable by name at the floor.
"""

from types import SimpleNamespace

import pytest


def _skill(name: str, desc: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=desc)


def _build(prompt_mod, skills, *, compact=False):
    return prompt_mod._build_skills_prompt_section(
        skills,
        available_skills=None,
        use_virtual_paths=False,
        prompt_language=None,
        compact=compact,
    )


@pytest.fixture()
def prompt_mod():
    from evoflow.agents.lead_agent import prompt

    return prompt


def test_typical_catalog_keeps_full_descriptions(prompt_mod):
    desc = "在平自动填入车辆信息并完成报价计算。"
    skills = [_skill(f"skill-{i}", desc) for i in range(3)]

    section = _build(prompt_mod, skills)

    assert section.count(desc) == 3
    assert "<description>" in section


def test_oversized_catalog_degrades_to_sentence_capped(prompt_mod, monkeypatch):
    from evoflow.assets import injection_budget

    long_desc = "这是一段很长的技能描述。" * 200  # ~1600 chars each
    skills = [_skill(f"s{i}", long_desc) for i in range(8)]
    monkeypatch.setattr(injection_budget, "TIER0_SKILLS_SECTION_CHARS", 3000)

    section = _build(prompt_mod, skills)

    assert long_desc not in section
    assert "…" in section
    assert section.count("<description>") == 8
    assert section.count("skill:s") == 8


def test_pathological_catalog_degrades_to_names_only(prompt_mod, monkeypatch):
    from evoflow.assets import injection_budget

    long_desc = "这是一段很长的技能描述。" * 200
    skills = [_skill(f"s{i}", long_desc) for i in range(8)]
    monkeypatch.setattr(injection_budget, "TIER0_SKILLS_SECTION_CHARS", 800)

    section = _build(prompt_mod, skills)

    assert "<description>" not in section
    for i in range(8):
        assert f"<name>s{i}</name>" in section
        assert f"<location>skill:s{i}</location>" in section


def test_compact_mode_stays_capped(prompt_mod):
    desc = "这是一个超过一百六十字符上限的技能描述。" * 20
    skills = [_skill("big-skill", desc)]

    section = _build(prompt_mod, skills, compact=True)

    assert desc not in section
    assert "…" in section

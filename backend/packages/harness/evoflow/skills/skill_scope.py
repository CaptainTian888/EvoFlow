"""Skill discovery scope / precedence (native-style multi-root)."""

from __future__ import annotations

from enum import IntEnum


class SkillScope(IntEnum):
    """Higher ``value`` wins when two skills share the same ``name``.

    Ordering: system-provided defaults < plugin-contributed (system add-on)
    < user-defined scopes. A plugin skill therefore outranks a same-named
    system skill but never shadows a skill the user defined themselves.
    """

    SYSTEM = 10
    PUBLIC = 20  # legacy primary ~/.evoflow/skills public/ (install-wide, system-seeded)
    EXTERNAL = 25  # plugin-contributed + config extra roots (system add-on)
    ORG = 30  # scopes/org/<id>/skills
    REPO = 35  # workspace .evoflow/skills
    GROUP = 40  # scopes/group/<id>/skills
    CUSTOM = 45  # legacy custom under primary (user-defined)
    PERSONAL = 50  # scopes/personal/<id>/skills — per-user overrides

"""ZCode embedded-search branch gate.

Source: ZCode/apps/zcode-cli/packages/core/src/embedded-search/capability.ts
Default enters the provider-visible embedded search branch. Bash find/grep prelude
injection is controlled by the execution layer and must not change the tool surface
just because the current shell cannot inject functions.
"""

from __future__ import annotations

# 默认进入 provider-visible embedded search branch。
ENABLE_EMBEDDED_SEARCH_BRANCH = True


def resolve_embedded_search_branch_capability(*, bash_available: bool, embedded_search_branch_enabled: bool | None = None) -> bool:
    branch_enabled = ENABLE_EMBEDDED_SEARCH_BRANCH if embedded_search_branch_enabled is None else embedded_search_branch_enabled
    if not branch_enabled:
        return False
    if not bash_available:
        return False
    return True

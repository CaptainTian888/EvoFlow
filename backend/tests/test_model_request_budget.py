"""Unit tests for vendor-request timeout / retry normalization.

Regression guard for the「生成中…」stall: the legacy default was
``request_timeout=600`` with ``max_retries=2``, so a gateway that accepted the
socket but never streamed a first token held the UI for up to 30 minutes
(600s x 3). Rows written before the fix still carry those literals in the DB,
so the resolvers must clamp on read, not just lower the default.

Run: cd backend && python -m pytest tests/test_model_request_budget.py -v
"""

from __future__ import annotations

import pytest

from evoflow.config.model_config import (
    _MAX_RETRIES_CEILING,
    _REQUEST_TIMEOUT_CEILING,
    DEFAULT_MODEL_MAX_RETRIES,
    DEFAULT_MODEL_REQUEST_TIMEOUT,
    resolve_model_max_retries,
    resolve_model_request_timeout,
)


class TestRequestTimeout:
    def test_unset_falls_back_to_default(self) -> None:
        assert resolve_model_request_timeout(None) == DEFAULT_MODEL_REQUEST_TIMEOUT
        assert resolve_model_request_timeout(0) == DEFAULT_MODEL_REQUEST_TIMEOUT
        assert resolve_model_request_timeout(-1) == DEFAULT_MODEL_REQUEST_TIMEOUT

    def test_default_is_within_ceiling(self) -> None:
        assert DEFAULT_MODEL_REQUEST_TIMEOUT <= _REQUEST_TIMEOUT_CEILING

    def test_legacy_600_row_is_clamped(self) -> None:
        # The regression: rows persisted with the old literal must not keep 600.
        assert resolve_model_request_timeout(600) == _REQUEST_TIMEOUT_CEILING

    def test_explicit_value_below_ceiling_is_preserved(self) -> None:
        assert resolve_model_request_timeout(45) == 45
        assert resolve_model_request_timeout(300) == 300

    def test_anything_above_ceiling_is_clamped(self) -> None:
        assert resolve_model_request_timeout(900) == _REQUEST_TIMEOUT_CEILING


class TestMaxRetries:
    def test_unset_falls_back_to_default(self) -> None:
        assert resolve_model_max_retries(None) == DEFAULT_MODEL_MAX_RETRIES
        assert resolve_model_max_retries(-1) == DEFAULT_MODEL_MAX_RETRIES

    def test_default_is_within_ceiling(self) -> None:
        assert DEFAULT_MODEL_MAX_RETRIES <= _MAX_RETRIES_CEILING

    def test_zero_is_respected(self) -> None:
        # Operators may opt out of retries entirely.
        assert resolve_model_max_retries(0) == 0

    def test_above_ceiling_is_clamped(self) -> None:
        assert resolve_model_max_retries(9) == _MAX_RETRIES_CEILING

    def test_legacy_2_row_still_allowed(self) -> None:
        # 2 was the legacy default and is not itself harmful; the ceiling, not a
        # blanket rewrite, is what bounds the worst case.
        assert resolve_model_max_retries(2) == 2


class TestWorstCaseStall:
    def test_stall_budget_is_bounded(self) -> None:
        """Worst case = timeout x (retries + 1). Legacy was 600 x 3 = 1800s."""
        attempts = DEFAULT_MODEL_MAX_RETRIES + 1
        worst_case_s = DEFAULT_MODEL_REQUEST_TIMEOUT * attempts
        assert worst_case_s <= 600, f"worst-case stall regressed to {worst_case_s}s"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

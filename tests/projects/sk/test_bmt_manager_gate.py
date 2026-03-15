"""Tests for gate comparison: config is the single source of truth (no bmt_id override)."""

from __future__ import annotations

from gcp.image.projects.shared import bmt_manager_base as base


def test_normalize_comparison_gte() -> None:
    assert base._normalize_comparison("gte") == "gte"
    assert base._normalize_comparison(" GtE ") == "gte"


def test_normalize_comparison_lte() -> None:
    assert base._normalize_comparison("lte") == "lte"
    assert base._normalize_comparison(" LTE ") == "lte"


def test_normalize_comparison_config_is_truth_no_override() -> None:
    """Config comparison is used as-is; no bmt_id-based override."""
    assert base._normalize_comparison("lte") == "lte"
    assert base._normalize_comparison("gte") == "gte"


def test_normalize_comparison_invalid_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="must be 'gte' or 'lte'"):
        base._normalize_comparison("gt")
    with pytest.raises(ValueError, match="must be 'gte' or 'lte'"):
        base._normalize_comparison("eq")

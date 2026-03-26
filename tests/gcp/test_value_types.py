"""Tests for backend.config.value_types."""

from __future__ import annotations

import pytest

from backend.config.value_types import (
    as_results_path,
    as_run_id,
    results_path_str,
    sanitize_run_id,
)

pytestmark = pytest.mark.unit


def test_sanitize_run_id_safe_chars() -> None:
    run_id = "gh-12345-1-sk-false_reject_namuh-abc123def456"
    assert sanitize_run_id(run_id) == run_id


def test_sanitize_run_id_replaces_unsafe() -> None:
    assert sanitize_run_id("foo/bar baz") == "foo-bar-baz"


def test_sanitize_run_id_strips_leading_trailing() -> None:
    assert sanitize_run_id("--abc--") == "abc"


def test_sanitize_run_id_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        sanitize_run_id("   ")


def test_sanitize_run_id_truncates_long() -> None:
    long_id = "a" * 300
    assert len(sanitize_run_id(long_id)) == 200


def test_as_run_id_returns_newtype() -> None:
    rid = as_run_id("abc-123")
    assert str(rid) == "abc-123"


def test_as_results_path_normalizes() -> None:
    rp = as_results_path(" /projects/sk/results/foo/ ")
    assert results_path_str(rp) == "projects/sk/results/foo"


def test_as_results_path_rejects_gs_uri() -> None:
    with pytest.raises(ValueError, match="bucket-relative"):
        as_results_path("gs://b/projects/sk/foo")


def test_as_results_path_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        as_results_path("  /  ")

"""Tests for GitHub Checks output UTF-8 clamping."""

from __future__ import annotations

import pytest

from gcp.image.github import github_checks

pytestmark = pytest.mark.unit


def test_clamp_utf8_by_bytes_noop_short() -> None:
    assert github_checks.clamp_utf8_by_bytes("hello") == "hello"


def test_clamp_utf8_by_bytes_truncates_multibyte() -> None:
    s = "é" * 40000  # 2 bytes per char in UTF-8
    out = github_checks.clamp_utf8_by_bytes(s, max_bytes=100)
    assert len(out.encode("utf-8")) <= 100
    out.encode("utf-8")  # valid unicode


def test_normalize_check_output_clamps_summary() -> None:
    huge = "x" * 100_000
    normalized = github_checks._normalize_check_output({"title": "t", "summary": huge, "text": "body"})
    assert len(normalized["summary"].encode("utf-8")) <= github_checks.GITHUB_CHECK_OUTPUT_FIELD_MAX_BYTES

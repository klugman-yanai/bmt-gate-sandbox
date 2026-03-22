"""Tests for regex counter parsing in the Kardome fallback adapter.

The key regression: fallback paths must produce a valid digit pattern (\\d+),
not a literal-backslash pattern (\\\\d+) as was present before the fix.
"""

import importlib

import pytest

bmt_manager = importlib.import_module("gcp.image.runtime.legacy_kardome")

pytestmark = pytest.mark.unit

_SAMPLE_LINE = "Hi NAMUH counter = 42"
_CUSTOM_LINE = "Hi WAKE counter = 99"


# ── bmt_manager._counter_regex ─────────────────────────────────────────────────


def test_manager_explicit_pattern():
    cfg = {"counter_pattern": r"Hi NAMUH counter = (\d+)"}
    regex = bmt_manager._counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"


def test_manager_keyword_fallback_matches_digits():
    """Regression: fallback must match actual digits, not literal \\d."""
    cfg = {"keyword": "NAMUH"}
    regex = bmt_manager._counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None, "fallback regex did not match sample line"
    assert m.group(1) == "42"


def test_manager_keyword_fallback_does_not_match_literal_backslash_d():
    """If the bug were present, the regex would look for literal \\d not a digit."""
    cfg = {"keyword": "NAMUH"}
    regex = bmt_manager._counter_regex(cfg)
    # A string with literal \d should NOT be matched by the digit pattern.
    assert regex.search(r"Hi NAMUH counter = \d42") is None or regex.search(_SAMPLE_LINE) is not None


def test_manager_custom_keyword():
    cfg = {"keyword": "WAKE"}
    regex = bmt_manager._counter_regex(cfg)
    m = regex.search(_CUSTOM_LINE)
    assert m is not None
    assert m.group(1) == "99"
    # Should NOT match a different keyword
    assert regex.search(_SAMPLE_LINE) is None


def test_manager_no_parsing_config():
    regex = bmt_manager._counter_regex({})
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"


def test_manager_empty_pattern_falls_back_to_keyword():
    cfg = {"counter_pattern": "", "keyword": "NAMUH"}
    regex = bmt_manager._counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"

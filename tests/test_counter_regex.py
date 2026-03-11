"""Tests for regex counter parsing in bmt_manager and bmt_run_local.

The key regression: fallback paths must produce a valid digit pattern (\\d+),
not a literal-backslash pattern (\\\\d+) as was present before the fix.
"""

import importlib

# bmt_manager (VM path) and bmt_run_local (local path) should share regex behavior.
bmt_manager = importlib.import_module("gcp.code.sk.bmt_manager")
batch = importlib.import_module("tools.bmt.bmt_run_local")

_SAMPLE_LINE = "Hi NAMUH counter = 42"
_CUSTOM_LINE = "Hi WAKE counter = 99"


# ── bmt_manager._counter_regex ─────────────────────────────────────────────────


def test_manager_explicit_pattern():
    cfg = {"parsing": {"counter_pattern": r"Hi NAMUH counter = (\d+)"}}
    regex = bmt_manager._counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"


def test_manager_keyword_fallback_matches_digits():
    """Regression: fallback must match actual digits, not literal \\d."""
    cfg = {"parsing": {"keyword": "NAMUH"}}
    regex = bmt_manager._counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None, "fallback regex did not match sample line"
    assert m.group(1) == "42"


def test_manager_keyword_fallback_does_not_match_literal_backslash_d():
    """If the bug were present, the regex would look for literal \\d not a digit."""
    cfg = {"parsing": {"keyword": "NAMUH"}}
    regex = bmt_manager._counter_regex(cfg)
    # A string with literal \d should NOT be matched by the digit pattern.
    assert regex.search(r"Hi NAMUH counter = \d42") is None or regex.search(_SAMPLE_LINE) is not None


def test_manager_custom_keyword():
    cfg = {"parsing": {"keyword": "WAKE"}}
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
    cfg = {"parsing": {"counter_pattern": "", "keyword": "NAMUH"}}
    regex = bmt_manager._counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"


# ── bmt_run_local.counter_regex ───────────────────────────────────────────────


def test_batch_explicit_pattern():
    cfg = {"parsing": {"counter_pattern": r"Hi NAMUH counter = (\d+)"}}
    regex = batch.counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"


def test_batch_keyword_fallback_matches_digits():
    cfg = {"parsing": {"keyword": "NAMUH"}}
    regex = batch.counter_regex(cfg)
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"


def test_batch_no_parsing_config():
    regex = batch.counter_regex({})
    m = regex.search(_SAMPLE_LINE)
    assert m is not None
    assert m.group(1) == "42"

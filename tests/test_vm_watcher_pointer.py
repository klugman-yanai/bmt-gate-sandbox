"""Tests for VM watcher pointer and aggregation helpers (Phase 2)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure remote/ is on path so we can import vm_watcher
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "remote") not in sys.path:
    sys.path.insert(0, str(_ROOT / "remote"))

import vm_watcher as watcher  # type: ignore[import-not-found]  # noqa: E402


def test_results_prefix_from_ci_verdict_uri_basic():
    """Derive results_prefix from snapshot ci_verdict URI."""
    bucket_root = "gs://my-bucket"
    uri = "gs://my-bucket/sk/results/false_rejects/snapshots/run-123/ci_verdict.json"
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, uri) == "sk/results/false_rejects"


def test_results_prefix_from_ci_verdict_uri_with_bucket_prefix():
    """Derive results_prefix when bucket has a prefix."""
    bucket_root = "gs://my-bucket/prefix"
    uri = "gs://my-bucket/prefix/sk/results/false_rejects/snapshots/run-456/ci_verdict.json"
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, uri) == "sk/results/false_rejects"


def test_results_prefix_from_ci_verdict_uri_invalid_returns_none():
    """Return None when URI has no snapshots segment or is empty."""
    bucket_root = "gs://my-bucket"
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, "") is None
    assert watcher._results_prefix_from_ci_verdict_uri(bucket_root, "gs://other/sk/results/x.json") is None
    assert (
        watcher._results_prefix_from_ci_verdict_uri(bucket_root, "gs://my-bucket/sk/results/false_rejects/latest.json")
        is None
    )


def test_aggregate_verdicts_from_summaries_all_pass():
    """All pass/warning -> success."""
    summaries = [
        {"status": "pass", "reason_code": "score_gte_last"},
        {"status": "warning", "reason_code": "bootstrap_without_baseline"},
    ]
    state, desc = watcher._aggregate_verdicts_from_summaries(summaries)
    assert state == "success"
    assert "2/2" in desc


def test_aggregate_verdicts_from_summaries_one_fail():
    """One fail -> failure."""
    summaries = [
        {"status": "pass"},
        {"status": "fail", "reason_code": "score_below_last"},
    ]
    state, desc = watcher._aggregate_verdicts_from_summaries(summaries)
    assert state == "failure"
    assert "1" in desc and "failed" in desc


def test_aggregate_verdicts_from_summaries_none_treated_as_fail():
    """None summary (e.g. manager didn't write summary) counts as fail."""
    state, desc = watcher._aggregate_verdicts_from_summaries([None, {"status": "pass"}])
    assert state == "failure"
    assert "1" in desc and "failed" in desc

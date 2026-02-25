"""Tests for VM watcher pointer and aggregation helpers (Phase 2)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure remote/code is on path so we can import vm_watcher
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "remote" / "code") not in sys.path:
    sys.path.insert(0, str(_ROOT / "remote" / "code"))

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


def test_run_handshake_uri_from_trigger_uri():
    trigger_uri = "gs://my-bucket/pfx/triggers/runs/123456.json"
    expected = "gs://my-bucket/pfx/triggers/acks/123456.json"
    assert watcher._run_handshake_uri_from_trigger_uri(trigger_uri) == expected


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
    assert "1" in desc
    assert "failed" in desc


def test_aggregate_verdicts_from_summaries_none_treated_as_fail():
    """None summary (e.g. manager didn't write summary) counts as fail."""
    state, desc = watcher._aggregate_verdicts_from_summaries([None, {"status": "pass"}])
    assert state == "failure"
    assert "1" in desc
    assert "failed" in desc


def test_run_id_from_json_uri():
    assert watcher._run_id_from_json_uri("gs://bucket/pfx/triggers/acks/1234.json") == "1234"
    assert watcher._run_id_from_json_uri("gs://bucket/pfx/triggers/acks/not-json.txt") is None


def test_workflow_run_sort_key_prefers_numeric():
    assert watcher._workflow_run_sort_key("123") > watcher._workflow_run_sort_key("abc")
    assert watcher._workflow_run_sort_key("200") > watcher._workflow_run_sort_key("100")


def test_trim_trigger_family_keeps_recent_and_explicit(monkeypatch):
    listed = [
        "gs://b/p/triggers/acks/100.json",
        "gs://b/p/triggers/acks/101.json",
        "gs://b/p/triggers/acks/102.json",
        "gs://b/p/triggers/acks/xyz.json",
    ]
    deleted: list[str] = []

    monkeypatch.setattr(watcher, "_gcloud_ls", lambda *_args, **_kwargs: listed)
    monkeypatch.setattr(
        watcher,
        "_gcloud_rm",
        lambda uri, recursive=False: deleted.append(f"{uri}|{recursive}") or True,
    )

    watcher._trim_trigger_family(
        "gs://b/p/triggers/acks/",
        keep_ids={"101"},
        keep_recent=2,
    )

    assert deleted == [
        "gs://b/p/triggers/acks/100.json|False",
        "gs://b/p/triggers/acks/xyz.json|False",
    ]


def test_cleanup_workflow_artifacts_targets_prefixed_and_base_status(monkeypatch):
    calls: list[tuple[str, set[str], int]] = []

    def _capture(prefix: str, *, keep_ids: set[str], keep_recent: int) -> None:
        calls.append((prefix, set(keep_ids), keep_recent))

    monkeypatch.setattr(watcher, "_trim_trigger_family", _capture)

    watcher._cleanup_workflow_artifacts(
        runtime_bucket_root="gs://my-bucket/my-prefix/runtime",
        keep_workflow_ids={"222"},
    )

    prefixes = {c[0] for c in calls}
    assert "gs://my-bucket/my-prefix/runtime/triggers/acks/" in prefixes
    assert "gs://my-bucket/my-prefix/runtime/triggers/status/" in prefixes
    assert len(prefixes) == 2
    assert all(c[1] == {"222"} for c in calls)
    assert all(c[2] == watcher._KEEP_RECENT_WORKFLOW_FILES for c in calls)


def test_cleanup_legacy_result_history_deletes_archive_and_logs(monkeypatch):
    removed: list[tuple[str, bool]] = []

    def _capture(uri: str, *, recursive: bool = False) -> bool:
        removed.append((uri, recursive))
        return True

    monkeypatch.setattr(watcher, "_gcloud_rm", _capture)

    watcher._cleanup_legacy_result_history("gs://b/p", "sk/results/false_rejects")

    assert removed == [
        ("gs://b/p/sk/results/archive", True),
        ("gs://b/p/sk/results/logs/false_rejects", True),
    ]

"""Tests for .github/scripts/ci/models.py — pure functions only, no I/O."""

import pytest

from ci import models

# ── normalize_status ──────────────────────────────────────────────────────────


def test_normalize_status_valid():
    assert models.normalize_status("pass") == "pass"
    assert models.normalize_status("warning") == "warning"
    assert models.normalize_status("fail") == "fail"
    assert models.normalize_status("timeout") == "timeout"


def test_normalize_status_case_insensitive():
    assert models.normalize_status("PASS") == "pass"
    assert models.normalize_status("  Fail  ") == "fail"


def test_normalize_status_invalid():
    assert models.normalize_status("unknown") is None
    assert models.normalize_status("") is None
    assert models.normalize_status("error") is None


# ── sanitize_run_id ───────────────────────────────────────────────────────────


def test_sanitize_run_id_safe_chars():
    run_id = "gh-12345-1-sk-false_reject_namuh-abc123def456"
    assert models.sanitize_run_id(run_id) == run_id


def test_sanitize_run_id_replaces_unsafe():
    assert models.sanitize_run_id("foo/bar baz") == "foo-bar-baz"


def test_sanitize_run_id_strips_leading_trailing():
    assert models.sanitize_run_id("--abc--") == "abc"


def test_sanitize_run_id_empty_raises():
    with pytest.raises(ValueError):
        models.sanitize_run_id("   ")


def test_sanitize_run_id_truncates_long():
    long_id = "a" * 300
    assert len(models.sanitize_run_id(long_id)) == 200


# ── decision_for_counts ───────────────────────────────────────────────────────


def test_decision_timeout_takes_priority():
    assert models.decision_for_counts(5, 2, 1, 1) == models.DECISION_TIMEOUT


def test_decision_fail():
    assert models.decision_for_counts(3, 0, 1, 0) == models.DECISION_REJECTED


def test_decision_warning():
    assert models.decision_for_counts(3, 2, 0, 0) == models.DECISION_ACCEPTED_WITH_WARNINGS


def test_decision_accepted():
    assert models.decision_for_counts(1, 0, 0, 0) == models.DECISION_ACCEPTED


def test_decision_all_zero_returns_timeout():
    assert models.decision_for_counts(0, 0, 0, 0) == models.DECISION_TIMEOUT


# ── decision_exit ────────────────────────────────────────────────────────────


def test_decision_exit_accepted_is_zero():
    assert models.decision_exit(models.DECISION_ACCEPTED) == 0
    assert models.decision_exit(models.DECISION_ACCEPTED_WITH_WARNINGS) == 0


def test_decision_exit_rejected_nonzero():
    assert models.decision_exit(models.DECISION_REJECTED) != 0
    assert models.decision_exit(models.DECISION_TIMEOUT) != 0


# ── URI helpers ───────────────────────────────────────────────────────────────


def test_code_bucket_root_uri_fixed():
    """Fixed code root: gs://<bucket>/code (no prefix argument)."""
    assert models.code_bucket_root_uri("my-bucket") == "gs://my-bucket/code"


def test_runtime_bucket_root_uri_fixed():
    """Fixed runtime root: gs://<bucket>/runtime (no prefix argument)."""
    assert models.runtime_bucket_root_uri("my-bucket") == "gs://my-bucket/runtime"


def test_snapshot_verdict_uri():
    uri = models.snapshot_verdict_uri("gs://b", "sk/results/false_rejects", "run-abc")
    assert uri == "gs://b/sk/results/false_rejects/snapshots/run-abc/ci_verdict.json"


def test_current_pointer_uri():
    uri = models.current_pointer_uri("gs://b", "sk/results/false_rejects")
    assert uri == "gs://b/sk/results/false_rejects/current.json"


def test_run_trigger_uri():
    uri = models.run_trigger_uri("gs://b/runtime", "123456")
    assert uri == "gs://b/runtime/triggers/runs/123456.json"


def test_run_trigger_uri_with_prefix():
    uri = models.run_trigger_uri("gs://b/team/runtime", "123456")
    assert uri == "gs://b/team/runtime/triggers/runs/123456.json"


def test_run_handshake_uri():
    uri = models.run_handshake_uri("gs://b/runtime", "123456")
    assert uri == "gs://b/runtime/triggers/acks/123456.json"


def test_run_handshake_uri_with_prefix():
    uri = models.run_handshake_uri("gs://b/team/runtime", "123456")
    assert uri == "gs://b/team/runtime/triggers/acks/123456.json"


def test_run_status_uri():
    uri = models.run_status_uri("gs://b/runtime", "123456")
    assert uri == "gs://b/runtime/triggers/status/123456.json"


# ── CloudVerdict.from_payload ─────────────────────────────────────────────────


def test_cloud_verdict_from_payload_basic():
    payload = {
        "run_id": "run-1",
        "project_id": "sk",
        "bmt_id": "false_reject_namuh",
        "status": "pass",
        "reason_code": "score_gte_last",
        "aggregate_score": 42.0,
        "runner": {"name": "kardome", "build_id": "v1", "source_ref": "main"},
    }
    v = models.CloudVerdict.from_payload(payload)
    assert v.run_id == "run-1"
    assert v.status == "pass"
    assert v.aggregate_score == 42.0
    assert v.runner.name == "kardome"
    assert v.gate is None


def test_cloud_verdict_from_payload_missing_fields():
    v = models.CloudVerdict.from_payload({})
    assert v.run_id == ""
    assert v.aggregate_score is None
    assert v.runner.name == "unknown"


def test_cloud_verdict_from_payload_preserves_raw():
    payload = {"run_id": "r", "status": "fail", "reason_code": "runner_failures"}
    v = models.CloudVerdict.from_payload(payload)
    assert v.raw is payload

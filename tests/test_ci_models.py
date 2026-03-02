"""Tests for .github/bmt/cli/shared/__init__.py — pure functions only, no I/O."""

import pytest
from cli import shared as models

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

"""Tests for .github/bmt/ci/core.py — pure functions only, no I/O."""

import pytest
from backend.config import value_types as vt
from backend.config.decisions import GateDecision
from bmtgate import core as models

pytestmark = pytest.mark.unit


def test_sanitize_run_id_is_value_types_reexport() -> None:
    # bmtgate.contract.value_types has its own copy; verify behavioural equivalence (drift guard).
    assert models.sanitize_run_id("hello world") == vt.sanitize_run_id("hello world")
    assert models.sanitize_run_id("a/b/c") == vt.sanitize_run_id("a/b/c")


# ── decision_exit ────────────────────────────────────────────────────────────


def test_decision_exit_accepted_is_zero():
    assert models.decision_exit(models.DECISION_ACCEPTED) == 0
    assert models.decision_exit(models.DECISION_ACCEPTED_WITH_WARNINGS) == 0


def test_decision_exit_rejected_nonzero():
    assert models.decision_exit(models.DECISION_REJECTED) != 0
    assert models.decision_exit(models.DECISION_TIMEOUT) != 0


def test_decision_exit_accepts_gate_decision_enum():
    assert models.decision_exit(GateDecision.ACCEPTED) == 0
    assert models.decision_exit(GateDecision.REJECTED) != 0


def test_decision_exit_unknown_string_nonzero():
    assert models.decision_exit("not_a_real_decision") != 0


# ── URI helpers ───────────────────────────────────────────────────────────────


def test_bucket_root_uri():
    """Bucket root: gs://<bucket> (no code/ or runtime/ prefix)."""
    assert models.bucket_root_uri("my-bucket") == "gs://my-bucket"

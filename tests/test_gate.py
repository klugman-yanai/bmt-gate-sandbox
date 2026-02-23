"""Tests for compute_gate and resolve_status in run_sk_bmt_batch.py."""

import importlib
import sys

# run_sk_bmt_batch lives in devtools/; conftest.py adds devtools to sys.path.
batch = importlib.import_module("run_sk_bmt_batch")
compute_gate = batch.compute_gate
resolve_status = batch.resolve_status
effective_gate_comparison = batch._effective_gate_comparison


# ── compute_gate ──────────────────────────────────────────────────────────────


def test_runner_failures_override_gate():
    gate = compute_gate("gte", current_score=10.0, previous_score=5.0, failed_count=1)
    assert gate["passed"] is False
    assert gate["reason"] == "runner_failures"


def test_bootstrap_manual_passes():
    gate = compute_gate("gte", current_score=5.0, previous_score=None, failed_count=0, run_context="manual")
    assert gate["passed"] is True
    assert gate["reason"] == "bootstrap_no_previous_result"
    assert gate["last_score"] is None


def test_bootstrap_pr_fails():
    gate = compute_gate("gte", current_score=5.0, previous_score=None, failed_count=0, run_context="pr")
    assert gate["passed"] is False
    assert gate["reason"] == "missing_previous_result"


def test_gte_passes_when_equal():
    gate = compute_gate("gte", current_score=10.0, previous_score=10.0, failed_count=0)
    assert gate["passed"] is True
    assert gate["reason"] == "score_gte_last"


def test_gte_passes_when_higher():
    gate = compute_gate("gte", current_score=11.0, previous_score=10.0, failed_count=0)
    assert gate["passed"] is True


def test_gte_fails_when_lower():
    gate = compute_gate("gte", current_score=9.0, previous_score=10.0, failed_count=0)
    assert gate["passed"] is False
    assert gate["reason"] == "score_below_last"


def test_lte_passes_when_lower():
    gate = compute_gate("lte", current_score=4.0, previous_score=5.0, failed_count=0)
    assert gate["passed"] is True
    assert gate["reason"] == "score_lte_last"


def test_lte_fails_when_higher():
    gate = compute_gate("lte", current_score=6.0, previous_score=5.0, failed_count=0)
    assert gate["passed"] is False
    assert gate["reason"] == "score_above_last"


def test_false_reject_forces_gte_comparison():
    assert effective_gate_comparison("false_reject_namuh", "lte") == "gte"


def test_non_false_reject_keeps_lte_comparison():
    assert effective_gate_comparison("false_accept_namuh", "lte") == "lte"


# ── resolve_status ────────────────────────────────────────────────────────────


def test_resolve_status_fail():
    gate = {"passed": False, "reason": "score_below_last"}
    status, reason = resolve_status(gate, {})
    assert status == "fail"
    assert reason == "score_below_last"


def test_resolve_status_bootstrap_warning():
    gate = {"passed": True, "reason": "bootstrap_no_previous_result"}
    policy = {"bootstrap_without_baseline": True}
    status, reason = resolve_status(gate, policy)
    assert status == "warning"
    assert reason == "bootstrap_without_baseline"


def test_resolve_status_bootstrap_pass_when_policy_disabled():
    gate = {"passed": True, "reason": "bootstrap_no_previous_result"}
    policy = {"bootstrap_without_baseline": False}
    status, reason = resolve_status(gate, policy)
    assert status == "pass"


def test_resolve_status_normal_pass():
    gate = {"passed": True, "reason": "score_gte_last"}
    status, reason = resolve_status(gate, {})
    assert status == "pass"
    assert reason == "score_gte_last"

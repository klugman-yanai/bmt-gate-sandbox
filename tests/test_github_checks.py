"""Tests for GitHub check markdown rendering."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LIB = _ROOT / "remote" / "code" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import github_checks  # type: ignore[import-not-found]  # noqa: E402

# ---------------------------------------------------------------------------
# Existing tests (updated for new column layout)
# ---------------------------------------------------------------------------


def test_render_results_table_shows_last_passing_score_when_available() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": "false_reject_namuh",
            "status": "pass",
            "passed": True,
            "aggregate_score": 56.833333333333336,
            "reason_code": "score_gte_last",
            "gate": {"last_score": 56.833333333333336},
            "orchestration_timing": {"duration_sec": 385},
        }
    ]
    aggregate = {"state": "PASS", "decision": "success", "reasons": []}

    table = github_checks.render_results_table(leg_summaries, aggregate)

    assert "sk" in table
    assert "false_reject_namuh" in table
    assert "✅ PASS" in table
    assert "56.8" in table
    assert "6m 25s" in table


def test_render_results_table_uses_top_level_last_score_fallback() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": "false_reject_namuh",
            "status": "pass",
            "passed": True,
            "aggregate_score": 42.0,
            "reason_code": "score_gte_last",
            "last_score": 41.25,
            "orchestration_timing": {"duration_sec": 59},
        }
    ]
    aggregate = {"state": "PASS", "decision": "success", "reasons": []}

    table = github_checks.render_results_table(leg_summaries, aggregate)

    assert "42.0" in table
    assert "41.2" in table
    assert "59s" in table


# ---------------------------------------------------------------------------
# New tests
# ---------------------------------------------------------------------------


def test_render_progress_markdown_no_refresh_text() -> None:
    legs: list[dict] = []
    result = github_checks.render_progress_markdown(legs, 60, None)
    assert "Refresh this page" not in result


def test_render_progress_markdown_has_timestamp() -> None:
    legs: list[dict] = []
    result = github_checks.render_progress_markdown(legs, 60, None)
    assert "UTC" in result


def test_human_reason_known_code() -> None:
    assert github_checks._human_reason("score_below_last") == "Score dropped below baseline"


def test_human_reason_unknown_code() -> None:
    assert github_checks._human_reason("some_unknown_code") == "some_unknown_code"


def test_render_results_table_no_redundant_header() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": "bmt1",
            "status": "pass",
            "passed": True,
            "aggregate_score": 50.0,
            "reason_code": "score_gte_last",
            "gate": {"last_score": 50.0},
            "orchestration_timing": {"duration_sec": 10},
        }
    ]
    aggregate = {"state": "PASS", "decision": "success", "reasons": []}
    table = github_checks.render_results_table(leg_summaries, aggregate)
    assert "## ✅" not in table
    assert "## ❌" not in table


def test_render_results_table_no_decision_line() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": "bmt1",
            "status": "pass",
            "passed": True,
            "aggregate_score": 50.0,
            "reason_code": "score_gte_last",
            "gate": {"last_score": 50.0},
            "orchestration_timing": {"duration_sec": 10},
        }
    ]
    aggregate = {"state": "PASS", "decision": "success", "reasons": []}
    table = github_checks.render_results_table(leg_summaries, aggregate)
    assert "**Decision:**" not in table


def test_render_results_table_next_steps_runner_failure() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": "bmt1",
            "status": "fail",
            "passed": False,
            "aggregate_score": 0.0,
            "reason_code": "runner_failures",
            "gate": {"last_score": 50.0},
            "orchestration_timing": {"duration_sec": 5},
        }
    ]
    aggregate = {"state": "FAIL", "decision": "failure", "reasons": ["runner_failures"]}
    table = github_checks.render_results_table(leg_summaries, aggregate)
    assert "Runner crash" in table
    assert "Next Steps" in table


def test_render_results_table_next_steps_score_regression() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": "bmt1",
            "status": "fail",
            "passed": False,
            "aggregate_score": 40.0,
            "reason_code": "score_below_last",
            "gate": {"last_score": 41.0, "tolerance_abs": 0.25},
            "delta_from_previous": -1.0,
            "orchestration_timing": {"duration_sec": 10},
        }
    ]
    aggregate = {"state": "FAIL", "decision": "failure", "reasons": []}
    table = github_checks.render_results_table(leg_summaries, aggregate)
    assert "Score regression" in table


def test_delta_str_within_grace_annotated() -> None:
    # delta = -0.2, tolerance = 0.25, passed = True → 80% of grace, should annotate
    result = github_checks._delta_str(-0.2, 0.25, passed=True)
    assert "80%" in result
    assert "±0.25" in result


def test_delta_str_outside_threshold_no_annotation() -> None:
    # delta = -0.1, tolerance = 0.25, passed = True → 40% of grace, below 50% threshold
    result = github_checks._delta_str(-0.1, 0.25, passed=True)
    assert "%" not in result


def test_delta_str_no_baseline() -> None:
    result = github_checks._delta_str(None, 0.25, passed=True)
    assert result == "—"


def test_delta_str_fail_no_annotation() -> None:
    # On fail, no grace annotation (only show annotation on passing legs)
    result = github_checks._delta_str(-0.2, 0.25, passed=False)
    assert "%" not in result


def test_render_results_table_human_reason_in_output() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": "bmt1",
            "status": "pass",
            "passed": True,
            "aggregate_score": 50.0,
            "reason_code": "score_gte_last",
            "gate": {"last_score": 50.0},
            "orchestration_timing": {"duration_sec": 10},
        }
    ]
    aggregate = {"state": "PASS", "decision": "success", "reasons": []}
    table = github_checks.render_results_table(leg_summaries, aggregate)
    assert "Score at or above baseline" in table
    assert "score_gte_last" not in table

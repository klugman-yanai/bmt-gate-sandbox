"""Tests for GitHub check markdown rendering."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LIB = _ROOT / "deploy" / "code" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import github_checks  # type: ignore[import-not-found]  # noqa: E402


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

    assert "| sk | false_reject_namuh | ✅ PASS | 56.8 | 56.8 | score_gte_last | 6m 25s |" in table


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

    assert "| sk | false_reject_namuh | ✅ PASS | 42.0 | 41.2 | score_gte_last | 59s |" in table

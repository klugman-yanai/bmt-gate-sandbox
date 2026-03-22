"""Tests for GitHub check markdown rendering."""

from __future__ import annotations

import json

from gcp.image.github import github_checks
from tests.support.repo_policy import SAMPLE_PROJECT, repo_stage_bmt_manifest


def _false_reject_bmt_id() -> str:
    manifest_path = repo_stage_bmt_manifest(SAMPLE_PROJECT, "false_rejects")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return str(manifest["bmt_id"])


def test_render_results_table_shows_last_passing_score_when_available() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": _false_reject_bmt_id(),
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

    assert f"| sk | {_false_reject_bmt_id()} | ✅ PASS | 56.8 | 56.8 |" in table
    assert "6m 25s" in table
    assert "score met or exceeded baseline" in table


def test_render_results_table_uses_top_level_last_score_fallback() -> None:
    leg_summaries = [
        {
            "project_id": "sk",
            "bmt_id": _false_reject_bmt_id(),
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

    assert f"| sk | {_false_reject_bmt_id()} | ✅ PASS | 42.0 | 41.2 |" in table
    assert "59s" in table
    assert "score met or exceeded baseline" in table

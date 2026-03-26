"""Unit tests for SK plugin score() and evaluate() with case failures."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

import pytest

from backend.config.bmt_domain_status import BmtLegStatus
from backend.runtime.sdk.results import CaseResult, ExecutionResult, ScoreResult

pytestmark = pytest.mark.unit

_SK_PLUGIN_SRC = str(Path(__file__).resolve().parents[2] / "benchmarks/projects/sk/plugin_workspaces/default/src")


def _make_plugin():
    """Import and instantiate SkPlugin."""
    if _SK_PLUGIN_SRC not in sys.path:
        sys.path.insert(0, _SK_PLUGIN_SRC)
    from sk_plugin.plugin import SkPlugin

    return SkPlugin()


def _case(
    case_id: str,
    namuh: float,
    *,
    status: Literal["ok", "failed"] = "ok",
    error: str = "",
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        input_path=Path(f"/data/{case_id}"),
        exit_code=0 if status == "ok" else 127,
        status=status,
        metrics={"namuh_count": namuh},
        error=error,
    )


def _exec_result(*cases: CaseResult) -> ExecutionResult:
    return ExecutionResult(execution_mode_used="kardome_legacy_stdout", case_results=list(cases))


def _make_context(*, comparison: str = "lte", tolerance: float = 0.25, **plugin_config: object):
    """Build a minimal mock context with plugin_config."""
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.bmt_manifest.plugin_config = {"comparison": comparison, "tolerance_abs": tolerance, **plugin_config}
    ctx.bmt_manifest.bmt_slug = "test_bmt"
    return ctx


def test_lte_plugin_config_yields_lower_better_direction() -> None:
    plugin = _make_plugin()
    result = _exec_result(_case("a.wav", 1))
    score = plugin.score(result, None, _make_context(comparison="lte"))
    assert score.extra["scoring_policy"]["score_direction_hint"] == "lower_better"
    verdict = plugin.evaluate(score, None, _make_context(comparison="lte"))
    assert verdict.summary.get("score_direction_label") == "lower better"


class TestScoreAggregation:
    def test_all_ok_cases_average_correctly(self) -> None:
        plugin = _make_plugin()
        result = _exec_result(_case("a.wav", 10), _case("b.wav", 90))
        score = plugin.score(result, None, _make_context())
        assert score.aggregate_score == 50.0
        assert score.metrics["case_count"] == 2
        assert score.metrics["cases_ok"] == 2
        assert score.metrics["cases_failed"] == 0
        assert len(score.metrics["case_outcomes"]) == 2
        assert score.extra["scoring_policy"]["reducer"] == "mean_ok_cases"
        assert score.extra["scoring_policy"]["schema_version"] == "2"
        assert score.extra["scoring_policy"]["score_direction_hint"] == "lower_better"

    def test_failed_cases_excluded_from_average(self) -> None:
        plugin = _make_plugin()
        result = _exec_result(
            _case("a.wav", 10),
            _case("b.wav", 0, status="failed", error="runner_exit_127"),
            _case("c.wav", 90),
        )
        score = plugin.score(result, None, _make_context())
        # Failed case excluded: average of [10, 90] = 50, not [10, 0, 90] = 33.3
        assert score.aggregate_score == 50.0
        assert score.metrics["case_count"] == 3
        assert score.metrics["cases_ok"] == 2
        assert score.metrics["cases_failed"] == 1
        assert score.metrics["cases_failed_ids"] == ["b.wav"]
        outcomes = score.metrics["case_outcomes"]
        assert any(o["case_id"] == "b.wav" and o["status"] == "failed" for o in outcomes)

    def test_all_cases_failed_score_is_zero(self) -> None:
        plugin = _make_plugin()
        result = _exec_result(
            _case("a.wav", 0, status="failed", error="runner_exit_127"),
        )
        score = plugin.score(result, None, _make_context())
        assert score.aggregate_score == 0.0
        assert score.metrics["cases_ok"] == 0
        assert score.metrics["cases_failed"] == 1


class TestEvaluateFailsOnCaseErrors:
    def test_zero_cases_fails_with_no_dataset_cases_reason(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=0.0,
            metrics={"case_count": 0, "cases_ok": 0, "cases_failed": 0},
        )
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.status == BmtLegStatus.FAIL.value
        assert verdict.reason_code == "no_dataset_cases"
        assert not verdict.passed

    def test_execute_exception_maps_to_plugin_execute_failed(self) -> None:
        plugin = _make_plugin()
        er = ExecutionResult(
            execution_mode_used="unknown",
            case_results=[
                CaseResult(
                    case_id="_execute_",
                    input_path=Path("/data"),
                    exit_code=-1,
                    status="failed",
                    metrics={},
                    error="RuntimeError:boom",
                )
            ],
            raw_summary={"sk_plugin_execute_exception": True},
        )
        score = plugin.score(er, None, _make_context())
        assert score.extra.get("sk_plugin_execute_exception") is True
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.reason_code == "plugin_execute_failed"
        assert verdict.status == BmtLegStatus.FAIL.value
        assert not verdict.passed

    def test_case_failures_fail_when_grace_is_zero(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 2, "cases_failed": 1, "cases_failed_ids": ["b.wav"]},
        )
        verdict = plugin.evaluate(score, None, _make_context(max_grace_case_failures=0))
        assert verdict.status == BmtLegStatus.FAIL.value
        assert verdict.reason_code == "runner_case_failures"
        assert not verdict.passed

    def test_one_case_failure_passes_with_default_grace(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 2, "cases_failed": 1, "cases_failed_ids": ["b.wav"]},
        )
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.status == BmtLegStatus.PASS.value
        assert verdict.reason_code == "case_failures_within_grace"
        assert verdict.passed
        assert verdict.summary.get("grace_case_failures") == 1
        assert verdict.summary.get("max_grace_case_failures") == 1

    def test_two_case_failures_exceed_default_grace(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=40.0,
            metrics={
                "case_count": 4,
                "cases_ok": 2,
                "cases_failed": 2,
                "cases_failed_ids": ["a.wav", "b.wav"],
            },
        )
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.reason_code == "runner_case_failures"
        assert not verdict.passed

    def test_no_case_failures_bootstrap_passes(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 3, "cases_failed": 0},
        )
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.status == BmtLegStatus.PASS.value
        assert verdict.reason_code == "bootstrap_without_baseline"

    def test_no_case_failures_with_baseline_uses_tolerance(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 3, "cases_failed": 0},
        )
        baseline = ScoreResult(aggregate_score=50.0, metrics={})
        verdict = plugin.evaluate(score, baseline, _make_context(comparison="lte"))
        assert verdict.status == BmtLegStatus.PASS.value
        assert verdict.reason_code == "score_within_tolerance"

    def test_grace_with_baseline_pass_keeps_case_failures_within_grace_reason(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 2, "cases_failed": 1, "cases_failed_ids": ["b.wav"]},
        )
        baseline = ScoreResult(aggregate_score=50.0, metrics={})
        verdict = plugin.evaluate(score, baseline, _make_context(comparison="lte"))
        assert verdict.passed
        assert verdict.reason_code == "case_failures_within_grace"

    def test_grace_does_not_override_score_fail_vs_baseline(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=80.0,
            metrics={"case_count": 3, "cases_ok": 2, "cases_failed": 1, "cases_failed_ids": ["b.wav"]},
        )
        baseline = ScoreResult(aggregate_score=10.0, metrics={})
        verdict = plugin.evaluate(score, baseline, _make_context(comparison="lte"))
        assert not verdict.passed
        assert verdict.reason_code == "score_outside_tolerance"

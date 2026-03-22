"""Unit tests for SK plugin score() and evaluate() with case failures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from gcp.image.config.bmt_domain_status import BmtLegStatus
from gcp.image.runtime.sdk.results import CaseResult, ExecutionResult, ScoreResult

pytestmark = pytest.mark.unit

_SK_PLUGIN_SRC = str(
    Path(__file__).resolve().parents[2]
    / "gcp/stage/projects/sk/plugin_workspaces/default/src"
)


def _make_plugin():
    """Import and instantiate SkPlugin."""
    if _SK_PLUGIN_SRC not in sys.path:
        sys.path.insert(0, _SK_PLUGIN_SRC)
    from sk_plugin.plugin import SkPlugin

    return SkPlugin()


def _case(case_id: str, namuh: float, *, status: str = "ok", error: str = "") -> CaseResult:
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


def _make_context(*, comparison: str = "lte", tolerance: float = 0.25):
    """Build a minimal mock context with plugin_config."""
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.bmt_manifest.plugin_config = {"comparison": comparison, "tolerance_abs": tolerance}
    return ctx


class TestScoreAggregation:
    def test_all_ok_cases_average_correctly(self) -> None:
        plugin = _make_plugin()
        result = _exec_result(_case("a.wav", 10), _case("b.wav", 90))
        score = plugin.score(result, None, _make_context())
        assert score.aggregate_score == 50.0
        assert score.metrics["case_count"] == 2
        assert score.metrics["cases_ok"] == 2
        assert score.metrics["cases_failed"] == 0

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
    def test_case_failures_force_fail_even_with_good_score(self) -> None:
        plugin = _make_plugin()
        score = ScoreResult(
            aggregate_score=50.0,
            metrics={"case_count": 3, "cases_ok": 2, "cases_failed": 1, "cases_failed_ids": ["b.wav"]},
        )
        verdict = plugin.evaluate(score, None, _make_context())
        assert verdict.status == BmtLegStatus.FAIL.value
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

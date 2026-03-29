"""Functional façade over :mod:`backend.runtime.sdk.gating` (stable import paths for older call sites)."""

from __future__ import annotations

from typing import Any

from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.gating import (
    DEFAULT_BASELINE_TOLERANCE_EVALUATOR,
    DEFAULT_PASS_THRESHOLD_EVALUATOR,
    BaselineToleranceEvaluator,
    PassThresholdEvaluator,
    PassThresholdPolicy,
)
from backend.runtime.sdk.plugin import BmtPlugin
from backend.runtime.sdk.results import ScoreResult, VerdictResult

__all__ = [
    "evaluate_baseline_tolerance_verdict",
    "evaluate_pass_threshold_verdict",
]


def evaluate_pass_threshold_verdict(
    score_result: ScoreResult,
    context: ExecutionContext,
    *,
    threshold_key: str = "pass_threshold",
    default_threshold: float = 1.0,
    reason_code_ok: str = "score_above_threshold",
    reason_code_fail: str = "score_below_threshold",
    evaluator: PassThresholdEvaluator | None = None,
) -> VerdictResult:
    """Pass when ``aggregate_score`` meets ``pass_threshold`` in ``plugin_config``."""
    policy = PassThresholdPolicy(
        threshold_key=threshold_key,
        default_threshold=default_threshold,
        reason_code_ok=reason_code_ok,
        reason_code_fail=reason_code_fail,
    )
    ev = evaluator or DEFAULT_PASS_THRESHOLD_EVALUATOR
    return ev.evaluate(score_result, context, policy=policy)


def evaluate_baseline_tolerance_verdict(
    *,
    plugin: BmtPlugin,
    context: ExecutionContext,
    score_result: ScoreResult,
    baseline: ScoreResult | None,
    direction_fields: dict[str, Any],
    plugin_execute_extra_keys: tuple[str, ...] = (),
    evaluator: BaselineToleranceEvaluator | None = None,
) -> VerdictResult:
    """Baseline + tolerance + grace-case policy (Kardome-style legs).

    Expects :attr:`~backend.runtime.sdk.results.ScoreResult.metrics` shaped like
    :meth:`CaseRunSummary.as_score_metrics`.
    """
    if evaluator is not None:
        ev = evaluator
    elif plugin_execute_extra_keys:
        ev = BaselineToleranceEvaluator(plugin_execute_extra_keys=plugin_execute_extra_keys)
    else:
        ev = DEFAULT_BASELINE_TOLERANCE_EVALUATOR
    return ev.evaluate(
        grace_policy=plugin,
        context=context,
        score_result=score_result,
        baseline=baseline,
        direction_fields=direction_fields,
    )

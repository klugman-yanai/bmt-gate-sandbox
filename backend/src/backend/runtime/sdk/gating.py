"""Gating policies and verdict evaluators (strategy-style composition over raw dicts).

Typical usage:

* **Tutorial / scaffold plugins** — :class:`PassThresholdEvaluator` with :class:`PassThresholdPolicy`.
* **Baseline + tolerance + grace** (e.g. Kardome audio) — :class:`BaselineToleranceEvaluator`.

Policies are immutable Pydantic models parsed from ``bmt.json`` ``plugin_config``. Evaluators are
small, explicit classes so tests can substitute policies or subclass for product-specific rules.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.config.bmt_domain_status import BmtLegStatus
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.protocols import SupportsGraceCaseLimits
from backend.runtime.sdk.results import ScoreResult, VerdictResult


class PassThresholdPolicy(BaseModel):
    """Configuration for a single numeric threshold on :attr:`ScoreResult.aggregate_score`."""

    model_config = ConfigDict(frozen=True)

    threshold_key: str = Field(
        default="pass_threshold",
        description="Key in ``plugin_config`` holding the minimum passing aggregate score.",
    )
    default_threshold: float = Field(
        default=1.0,
        ge=0.0,
        description="Used when the manifest key is missing or non-numeric.",
    )
    reason_code_ok: str = Field(
        default="score_above_threshold",
        description="Machine reason when the leg passes the threshold.",
    )
    reason_code_fail: str = Field(
        default="score_below_threshold",
        description="Machine reason when the leg fails the threshold.",
    )

    def resolve_threshold(self, plugin_config: Mapping[str, Any]) -> float:
        """Coerce manifest value to ``float``; fall back to :attr:`default_threshold`."""
        raw = plugin_config.get(self.threshold_key, self.default_threshold)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return self.default_threshold


class BaselineTolerancePolicy(BaseModel):
    """How an aggregate score is compared to a stored baseline."""

    model_config = ConfigDict(frozen=True)

    comparison: Literal["gte", "lte"] = Field(
        default="gte",
        description="``gte`` = higher is better; ``lte`` = lower is better (e.g. false alarms).",
    )
    tolerance_abs: float = Field(
        default=0.25,
        ge=0.0,
        description="Absolute slack applied when comparing to the baseline aggregate.",
    )

    @classmethod
    def from_plugin_config(cls, plugin_config: Mapping[str, Any]) -> BaselineTolerancePolicy:
        """Build from ``plugin_config`` with tolerant parsing of ``comparison`` and ``tolerance_abs``."""
        raw_comp = str(plugin_config.get("comparison", "gte")).strip().lower()
        comp: Literal["gte", "lte"] = "lte" if raw_comp == "lte" else "gte"
        raw_tol = plugin_config.get("tolerance_abs", 0.25)
        try:
            tol = float(raw_tol if raw_tol is not None else 0.25)
        except (TypeError, ValueError):
            tol = 0.25
        return cls(comparison=comp, tolerance_abs=max(0.0, tol))


class PassThresholdEvaluator:
    """Stateless evaluator: pass iff ``aggregate_score >= resolved_threshold``."""

    def evaluate(
        self,
        score_result: ScoreResult,
        context: ExecutionContext,
        *,
        policy: PassThresholdPolicy | None = None,
    ) -> VerdictResult:
        p = policy or PassThresholdPolicy()
        threshold = p.resolve_threshold(context.bmt_manifest.plugin_config)
        ok = score_result.aggregate_score >= threshold
        return VerdictResult(
            passed=ok,
            status=BmtLegStatus.PASS.value if ok else BmtLegStatus.FAIL.value,
            reason_code=p.reason_code_ok if ok else p.reason_code_fail,
            summary={
                "aggregate_score": score_result.aggregate_score,
                "threshold": threshold,
            },
        )


def _plugin_execute_failed(score_result: ScoreResult, extra_keys: tuple[str, ...]) -> bool:
    if score_result.extra.get("plugin_execute_exception"):
        return True
    return any(score_result.extra.get(k) for k in extra_keys)


class BaselineToleranceEvaluator:
    """Baseline comparison with per-case grace and optional execute-failure detection."""

    __slots__ = ("_extra_execute_keys", "_log")

    def __init__(
        self,
        *,
        plugin_execute_extra_keys: tuple[str, ...] = (),
        logger_: logging.Logger | None = None,
    ) -> None:
        self._extra_execute_keys = plugin_execute_extra_keys
        self._log = logger_ or logging.getLogger(__name__)

    def evaluate(
        self,
        *,
        grace_policy: SupportsGraceCaseLimits,
        context: ExecutionContext,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        direction_fields: Mapping[str, Any],
    ) -> VerdictResult:
        """Return a terminal verdict for this leg.

        Args:
            grace_policy: Usually ``self`` on a :class:`~backend.runtime.sdk.plugin.BmtPlugin`.
            context: Current execution context (manifest + paths).
            score_result: Output of :meth:`~backend.runtime.sdk.plugin.BmtPlugin.score`.
            baseline: Prior aggregate for this BMT, or ``None`` on bootstrap runs.
            direction_fields: Extra summary keys (e.g. comparison hints for dashboards).
        """
        tol_policy = BaselineTolerancePolicy.from_plugin_config(context.bmt_manifest.plugin_config)
        cfg = context.bmt_manifest.plugin_config
        case_count = int(score_result.metrics.get("case_count", 0) or 0)

        if case_count == 0:
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="no_dataset_cases",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "case_count": 0,
                    **dict(direction_fields),
                },
            )

        if _plugin_execute_failed(score_result, self._extra_execute_keys):
            cases_failed = int(score_result.metrics.get("cases_failed", 0))
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="plugin_execute_failed",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "cases_failed": cases_failed,
                    "cases_failed_ids": score_result.metrics.get("cases_failed_ids", []),
                    **dict(direction_fields),
                },
            )

        grace = grace_policy.max_grace_case_failures(cfg)
        cases_failed = int(score_result.metrics.get("cases_failed", 0))
        failed_ids = list(score_result.metrics.get("cases_failed_ids", []))

        if cases_failed > grace:
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="runner_case_failures",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "cases_failed": cases_failed,
                    "cases_failed_ids": failed_ids,
                    "max_grace_case_failures": grace,
                    **dict(direction_fields),
                },
            )

        grace_meta: dict[str, Any] = {}
        if cases_failed > 0:
            grace_meta = {
                "max_grace_case_failures": grace,
                "grace_case_failures": cases_failed,
                "cases_failed_ids": failed_ids,
            }
            self._log.warning(
                "BMT %s: %s case(s) failed within grace (limit=%s): %s",
                context.bmt_manifest.bmt_slug,
                cases_failed,
                grace,
                failed_ids,
            )

        if baseline is None:
            return VerdictResult(
                passed=True,
                status=BmtLegStatus.PASS.value,
                reason_code="case_failures_within_grace" if cases_failed > 0 else "bootstrap_without_baseline",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "baseline_score": None,
                    **dict(direction_fields),
                    **grace_meta,
                },
            )

        if tol_policy.comparison == "lte":
            passed = score_result.aggregate_score <= baseline.aggregate_score + tol_policy.tolerance_abs
        else:
            passed = score_result.aggregate_score >= baseline.aggregate_score - tol_policy.tolerance_abs

        if not passed:
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="score_outside_tolerance",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "baseline_score": baseline.aggregate_score,
                    "tolerance_abs": tol_policy.tolerance_abs,
                    **dict(direction_fields),
                    **grace_meta,
                },
            )

        return VerdictResult(
            passed=True,
            status=BmtLegStatus.PASS.value,
            reason_code="case_failures_within_grace" if cases_failed > 0 else "score_within_tolerance",
            summary={
                "aggregate_score": score_result.aggregate_score,
                "baseline_score": baseline.aggregate_score,
                "tolerance_abs": tol_policy.tolerance_abs,
                **dict(direction_fields),
                **grace_meta,
            },
        )


# Module-level singletons for call sites that prefer functions (see :mod:`baseline_verdict`).
DEFAULT_PASS_THRESHOLD_EVALUATOR = PassThresholdEvaluator()
DEFAULT_BASELINE_TOLERANCE_EVALUATOR = BaselineToleranceEvaluator()

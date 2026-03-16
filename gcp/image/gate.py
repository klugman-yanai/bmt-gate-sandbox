"""Pure gate/verdict evaluation logic (L4 — imports from L0 constants and L1 models only).

ZERO dependencies on GCS, orchestration, or bmt_manager_base.
All functions are deterministic and testable without network or subprocess.
"""

from __future__ import annotations

from typing import Any

from gcp.image.config.constants import (
    REASON_DEMO_FORCE_PASS,
    REASON_RUNNER_FAILURES,
    REASON_RUNNER_TIMEOUT,
)
from gcp.image.models import GateResult


def normalize_comparison(comparison: str) -> str:
    """Normalize and validate gate comparison operator (gte/lte)."""
    normalized = comparison.strip().lower()
    if normalized not in ("gte", "lte"):
        raise ValueError(f"gate.comparison must be 'gte' or 'lte', got: {comparison!r}")
    return normalized


def gate_result(
    comparison: str,
    current_score: float,
    last_score: float | None,
    failed_count: int,
    tolerance_abs: float = 0.0,
    *,
    baseline_zero_is_missing: bool = True,
) -> GateResult:
    """Evaluate the gate — pure computation, no I/O."""
    if failed_count > 0:
        return GateResult(
            comparison=comparison,
            last_score=last_score,
            current_score=current_score,
            passed=False,
            reason=REASON_RUNNER_FAILURES,
            tolerance_abs=tolerance_abs,
        )

    if last_score is None or (baseline_zero_is_missing and last_score == 0):
        return GateResult(
            comparison=comparison,
            last_score=last_score,
            current_score=current_score,
            passed=True,
            reason="bootstrap_no_previous_result",
            tolerance_abs=tolerance_abs,
        )

    tol = abs(tolerance_abs)
    if comparison == "gte":
        passed = current_score >= last_score - tol
        reason = "score_gte_last" if passed else "score_below_last"
    elif comparison == "lte":
        passed = current_score <= last_score + tol
        reason = "score_lte_last" if passed else "score_above_last"
    else:
        raise ValueError(f"Unsupported gate comparison: {comparison}")

    return GateResult(
        comparison=comparison,
        last_score=last_score,
        current_score=current_score,
        passed=passed,
        reason=reason,
        tolerance_abs=tolerance_abs,
    )


def resolve_status(gate: GateResult | dict[str, Any], warning_policy: dict[str, Any]) -> tuple[str, str]:
    """Resolve gate outcome to (status, reason_code). status: pass|fail|warning."""
    if isinstance(gate, GateResult):
        passed = gate.passed
        reason = gate.reason
    else:
        passed = bool(gate.get("passed"))
        reason = str(gate.get("reason", "unknown"))

    if not passed:
        return "fail", reason

    if reason == "bootstrap_no_previous_result" and bool(warning_policy.get("bootstrap_without_baseline", False)):
        return "warning", "bootstrap_without_baseline"

    return "pass", reason


def all_failures_are_timeouts(file_results: list[dict[str, Any]]) -> bool:
    """True if every non-zero exit in file_results is a timeout (exit_code 124 + timeout_after_ error)."""
    failed = [r for r in file_results if int(r.get("exit_code", 0)) != 0]
    if not failed:
        return False
    for r in failed:
        if int(r.get("exit_code", 0)) != 124:
            return False
        err = (r.get("error") or "").strip()
        if err and "timeout_after_" not in err:
            return False
    return True


def apply_demo_override(status: str, reason_code: str, demo_force_pass: bool) -> tuple[str, str]:
    """Apply demo_force_pass override if configured."""
    if demo_force_pass and status == "fail":
        return "pass", REASON_DEMO_FORCE_PASS
    return status, reason_code


def refine_timeout_reason(reason_code: str, failed_count: int, file_results: list[dict[str, Any]]) -> str:
    """Upgrade runner_failures to runner_timeout if all failures are timeouts."""
    if reason_code == REASON_RUNNER_FAILURES and failed_count > 0 and all_failures_are_timeouts(file_results):
        return REASON_RUNNER_TIMEOUT
    return reason_code

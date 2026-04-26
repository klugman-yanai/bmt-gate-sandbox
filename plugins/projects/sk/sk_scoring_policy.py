"""SK project scoring policy: metric, aggregation, and direction hints for reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from bmt_sdk.results import CaseResult

PRIMARY_METRIC = "namuh_count"
DEFAULT_REDUCER: Literal["mean_ok_cases"] = "mean_ok_cases"
# Case-level failures (runner crashes, timeouts, parse failures) are logged and surfaced in
# per-case tables, but do not gate the leg verdict. This lets us validate that non-crashing
# inputs still behave as expected while we debug flaky runner stability.
DEFAULT_FAILURE_POLICY: Literal["ignore_case_failures"] = "ignore_case_failures"
MAX_CASE_ERROR_CHARS = 2000
# Bump when adding/removing keys in ``scoring_policy`` (see docs/adr/0003-score-extra-reporting-contract.md).
SCORING_POLICY_SCHEMA_VERSION = "3"


def normalize_comparison(plugin_config: dict[str, Any]) -> str:
    return str(plugin_config.get("comparison", "gte")).strip().lower()


def score_direction_hint(comparison: str) -> str:
    """Semantic hint for UI: lower aggregate is better vs higher."""
    return "lower_better" if comparison.strip().lower() == "lte" else "higher_better"


def score_direction_label(comparison: str) -> str:
    """Human label for Checks tables, e.g. ``lower better``."""
    return "lower better" if score_direction_hint(comparison) == "lower_better" else "higher better"


def scoring_policy_record(plugin_config: dict[str, Any]) -> dict[str, Any]:
    """Forensics + reporting: what the SK plugin used for this leg."""
    comparison = normalize_comparison(plugin_config)
    tolerance = float(plugin_config.get("tolerance_abs", 0.25) or 0.25)
    reducer = str(plugin_config.get("aggregation", "mean_ok_cases") or "mean_ok_cases").strip()
    if reducer != "mean_ok_cases":
        reducer = "mean_ok_cases"
    out: dict[str, Any] = {
        "schema_version": SCORING_POLICY_SCHEMA_VERSION,
        "primary_metric": PRIMARY_METRIC,
        "reducer": reducer,
        "failure_policy": DEFAULT_FAILURE_POLICY,
        "comparison": comparison,
        "tolerance_abs": tolerance,
        "score_direction_hint": score_direction_hint(comparison),
        "score_direction_label": score_direction_label(comparison),
    }
    hints = plugin_config.get("reporting_hints")
    if isinstance(hints, dict):
        out["reporting_hints"] = {str(k): v for k, v in hints.items()}
    return out


def aggregate_mean_ok_cases(case_results: list[CaseResult]) -> float:
    """Arithmetic average of ``namuh_count`` over passing cases (``status == \"ok\"``); failed cases excluded."""
    ok = [r for r in case_results if r.status == "ok"]
    if not ok:
        return 0.0
    values = [float(r.metrics.get(PRIMARY_METRIC, 0.0)) for r in ok]
    return sum(values) / len(values)


def build_case_outcomes(
    case_results: list[CaseResult], *, max_error_chars: int = MAX_CASE_ERROR_CHARS
) -> list[dict[str, Any]]:
    """Per-case rows for metrics, GCS ``case_digest.json``, and GitHub Checks (bounded errors)."""
    out: list[dict[str, Any]] = []
    for r in case_results:
        err = (r.error or "").strip()
        if len(err) > max_error_chars:
            err = err[: max_error_chars - 3] + "..."
        log_name = ""
        lp = r.artifacts.get("log_path")
        if isinstance(lp, str) and lp.strip():
            log_name = Path(lp).name
        out.append(
            {
                "case_id": r.case_id,
                "status": r.status,
                PRIMARY_METRIC: float(r.metrics.get(PRIMARY_METRIC, 0.0)),
                "error": err,
                "log_name": log_name,
            }
        )
    return out

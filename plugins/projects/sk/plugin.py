"""SK BMT plugin: use as a template. Read ``context.bmt_manifest.plugin_config`` for tuning."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, cast

from bmt_sdk import BmtPlugin
from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from pydantic import ValidationError
from sk_scoring_policy import (
    PRIMARY_METRIC,
    aggregate_mean_ok_cases,
    build_case_outcomes,
    scoring_policy_record,
)

from runtime.config.bmt_domain_status import BmtLegStatus
from runtime.kardome import AdaptiveKardomeExecutor
from runtime.kardome_batch_results import KardomeBatchFile
from runtime.kardome_runparams import KardomeRunparamsConfig, KardomeRunparamsExecutor
from runtime.stdout_counter_parse import StdoutCounterParseConfig

logger = logging.getLogger(__name__)


def _all_ok_cases_have_zero_namuh(case_outcomes: object) -> bool:
    """True when every ``status == \"ok\"`` row has ``namuh_count == 0`` (false_rejects / gte triage)."""
    if not isinstance(case_outcomes, list) or not case_outcomes:
        return False
    ok_rows: list[dict[str, Any]] = []
    for o in case_outcomes:
        if isinstance(o, dict):
            row = cast(dict[str, Any], o)
            if row.get("status") == "ok":
                ok_rows.append(row)
    if not ok_rows:
        return False
    for row in ok_rows:
        try:
            v = float(row.get(PRIMARY_METRIC, 0.0) or 0.0)
        except (TypeError, ValueError):
            return False
        if v != 0.0:
            return False
    return True


_BATCH_CMD_TIMEOUT_DEFAULT_SEC = 6 * 3600
_BATCH_CMD_TIMEOUT_MAX_SEC = 7 * 24 * 3600


def _batch_command_timeout_sec() -> float:
    raw = os.environ.get("BATCH_COMMAND_TIMEOUT_SEC", "").strip()
    if not raw:
        return float(_BATCH_CMD_TIMEOUT_DEFAULT_SEC)
    try:
        sec = int(raw)
    except ValueError:
        logger.warning("Invalid BATCH_COMMAND_TIMEOUT_SEC=%r; using default 6h", raw)
        return float(_BATCH_CMD_TIMEOUT_DEFAULT_SEC)
    if sec <= 0:
        return float(_BATCH_CMD_TIMEOUT_DEFAULT_SEC)
    return float(min(sec, _BATCH_CMD_TIMEOUT_MAX_SEC))


def _coerce_expected_channels(raw: Any) -> int | None:
    """Coerce plugin_config["expected_channels"] to a positive int, else ``None``.

    Missing/None/0/negative/non-numeric values all disable the channel gate. Keeps the
    leg JSON forgiving while preventing nonsensical values (e.g. ``"four"``) from leaking
    into the executor config.
    """
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Ignoring non-integer plugin_config.expected_channels=%r", raw)
        return None
    return value if value > 0 else None


def _coerce_forced_wav_path_keys_exclude(raw: Any) -> frozenset[str]:
    """``forced_wav_path_keys_exclude`` as upper-case keys; non-sequences log and return empty."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, list | tuple | set | frozenset):
        logger.warning("Ignoring non-sequence plugin_config.forced_wav_path_keys_exclude=%r", raw)
        return frozenset()
    keys: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            logger.warning("Ignoring non-string entry in forced_wav_path_keys_exclude: %r", item)
            continue
        keys.add(item.strip().upper())
    return frozenset(keys)


def _resolve_batch_results_file(workspace_root: Path, results_relpath: str) -> Path | None:
    """Return resolved results file path if it exists under workspace_root, else None."""
    rel = str(results_relpath).strip()
    if not rel:
        return None
    p = Path(rel)
    if p.is_absolute():
        logger.warning("batch_results_relpath must be relative, got %s", results_relpath)
        return None
    candidate = (workspace_root / rel).resolve()
    base = workspace_root.resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        logger.warning(
            "Batch results path escapes workspace (resolved %s not under %s)",
            candidate,
            base,
        )
        return None
    return candidate if candidate.is_file() else None


def _coerce_metric_name(raw: Any) -> str:
    """``plugin_config["metric_name"]`` for per-case rows; default ``namuh_count``."""
    if not isinstance(raw, str):
        return "namuh_count"
    name = raw.strip()
    return name or "namuh_count"


def _coerce_metric_json_keys(raw: Any) -> tuple[str, ...]:
    """Per-case .bmt.json keys to try for the primary metric (``plugin_config["metric_json_keys"]``)."""
    if raw is None:
        return ("namuh_count", "hi_namuh_count", "namuh", "hi_namuh")
    if not isinstance(raw, list | tuple):
        logger.warning("Ignoring non-sequence plugin_config.metric_json_keys=%r", raw)
        return ("namuh_count", "hi_namuh_count", "namuh", "hi_namuh")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            logger.warning("Ignoring non-string metric_json_keys entry: %r", item)
            continue
        s = item.strip()
        if s:
            out.append(s)
    return tuple(out) if out else ("namuh_count", "hi_namuh_count", "namuh", "hi_namuh")


class SkPlugin(BmtPlugin):
    """SK ``BmtPlugin``: optional batch JSON, else per-case runparams; policy in ``evaluate``."""

    plugin_name = "default"
    api_version = "v1"

    @staticmethod
    def _verdict_direction_fields(context: ExecutionContext) -> dict[str, Any]:
        sp = scoring_policy_record(context.bmt_manifest.plugin_config)
        return {
            "comparison": sp["comparison"],
            "score_direction_hint": sp["score_direction_hint"],
            "score_direction_label": sp["score_direction_label"],
        }

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        return PreparedAssets(
            dataset_root=context.dataset_root,
            workspace_root=context.workspace_root,
            runner_path=context.runner_path,
        )

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        try:
            validated_parse = StdoutCounterParseConfig.model_validate(context.bmt_manifest.plugin_config)
            per_case = KardomeRunparamsExecutor(
                KardomeRunparamsConfig(
                    runner_path=prepared_assets.runner_path or self._require_runner(context),
                    template_path=(Path.cwd() / context.bmt_manifest.runner.template_path).resolve(),
                    dataset_root=context.dataset_root,
                    runtime_root=context.workspace_root,
                    outputs_root=context.outputs_root,
                    logs_root=context.logs_root,
                    parsing=validated_parse.model_dump(mode="python", exclude_none=True),
                    enable_overrides=dict(context.bmt_manifest.plugin_config.get("enable_overrides", {})),
                    num_source_test=context.bmt_manifest.plugin_config.get("num_source_test"),
                    deps_root=context.deps_root,
                    expected_channels=_coerce_expected_channels(
                        context.bmt_manifest.plugin_config.get("expected_channels")
                    ),
                    forced_wav_path_keys_exclude=_coerce_forced_wav_path_keys_exclude(
                        context.bmt_manifest.plugin_config.get("forced_wav_path_keys_exclude")
                    ),
                    metric_name=_coerce_metric_name(context.bmt_manifest.plugin_config.get("metric_name")),
                    metric_json_keys=_coerce_metric_json_keys(
                        context.bmt_manifest.plugin_config.get("metric_json_keys")
                    ),
                )
            )

            return AdaptiveKardomeExecutor(
                execution_policy=context.bmt_manifest.execution.policy,
                run_batch=lambda: self._run_batch_probe(context, prepared_assets),
                parse_batch=lambda p: self._parse_batch_json(p, context.workspace_root),
                run_legacy=per_case.run,
            ).run()
        except Exception as exc:
            logger.exception("SK plugin execute failed for bmt=%s", context.bmt_manifest.bmt_slug)
            return ExecutionResult(
                execution_mode_used="unknown",
                case_results=[
                    CaseResult(
                        case_id="_execute_",
                        input_path=prepared_assets.dataset_root,
                        exit_code=-1,
                        status="failed",
                        metrics={},
                        artifacts={},
                        error=f"{type(exc).__name__}:{exc}",
                    )
                ],
                raw_summary={"sk_plugin_execute_exception": True},
            )

    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        ok_cases = [r for r in execution_result.case_results if r.status == "ok"]
        failed_cases = [r for r in execution_result.case_results if r.status != "ok"]
        aggregate = aggregate_mean_ok_cases(execution_result.case_results)
        case_outcomes = build_case_outcomes(execution_result.case_results)
        policy = scoring_policy_record(context.bmt_manifest.plugin_config)
        extra: dict[str, Any] = {
            "baseline_present": baseline is not None,
            "scoring_policy": policy,
        }
        if execution_result.raw_summary.get("sk_plugin_execute_exception"):
            extra["sk_plugin_execute_exception"] = True
        return ScoreResult(
            aggregate_score=aggregate,
            metrics={
                "case_count": len(execution_result.case_results),
                "cases_ok": len(ok_cases),
                "cases_failed": len(failed_cases),
                "cases_failed_ids": [r.case_id for r in failed_cases],
                "case_outcomes": case_outcomes,
            },
            extra=extra,
        )

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        comparison = str(context.bmt_manifest.plugin_config.get("comparison", "gte")).strip().lower()
        tolerance = float(context.bmt_manifest.plugin_config.get("tolerance_abs", 0.25) or 0.25)

        direction = self._verdict_direction_fields(context)
        case_count = int(score_result.metrics.get("case_count", 0) or 0)
        if case_count == 0:
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="no_dataset_cases",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "case_count": 0,
                    **direction,
                },
            )

        cases_failed = int(score_result.metrics.get("cases_failed", 0))
        cases_ok = int(score_result.metrics.get("cases_ok", 0) or 0)
        if score_result.extra.get("sk_plugin_execute_exception"):
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="plugin_execute_failed",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "cases_failed": cases_failed,
                    "cases_failed_ids": score_result.metrics.get("cases_failed_ids", []),
                    **direction,
                },
            )

        # If every case failed (runner crashes/timeouts/parse failures), we have no usable
        # signal for scoring and should fail the leg explicitly.
        if cases_ok == 0:
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="no_successful_cases",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "cases_failed": cases_failed,
                    "cases_failed_ids": score_result.metrics.get("cases_failed_ids", []),
                    **direction,
                },
            )

        # Higher-better legs (false_rejects): all NAMUH zeros usually mean a broken or
        # mis-tuned runner, but we **do not block the PR** — pass with an explicit warning
        # reason so Checks/summaries stay visible for triage.
        case_outcomes = score_result.metrics.get("case_outcomes")
        aggregate = float(score_result.aggregate_score or 0.0)
        gte_all_zero_kw_warn = (
            comparison == "gte"
            and cases_ok > 0
            and (
                _all_ok_cases_have_zero_namuh(case_outcomes)
                or (aggregate == 0.0 and (not isinstance(case_outcomes, list) or len(case_outcomes) == 0))
            )
        )
        if gte_all_zero_kw_warn and baseline is None:
            return VerdictResult(
                passed=True,
                status=BmtLegStatus.PASS.value,
                reason_code="all_zero_keyword_hits_warn",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "cases_ok": cases_ok,
                    "cases_failed": cases_failed,
                    "cases_failed_ids": score_result.metrics.get("cases_failed_ids", []),
                    "warning": (
                        "Every passing case reported NAMUH 0 on a higher-is-better leg. "
                        "Likely a runner or metrics bug; baseline not compared. PR not blocked."
                    ),
                    **direction,
                },
            )

        if baseline is None:
            return VerdictResult(
                passed=True,
                status=BmtLegStatus.PASS.value,
                reason_code="bootstrap_without_baseline",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "baseline_score": None,
                    **direction,
                },
            )
        if comparison == "lte":
            passed = score_result.aggregate_score <= baseline.aggregate_score + tolerance
        else:
            passed = score_result.aggregate_score >= baseline.aggregate_score - tolerance
        return VerdictResult(
            passed=passed,
            status=BmtLegStatus.PASS.value if passed else BmtLegStatus.FAIL.value,
            reason_code="score_within_tolerance" if passed else "score_outside_tolerance",
            summary={
                "aggregate_score": score_result.aggregate_score,
                "baseline_score": baseline.aggregate_score,
                "tolerance_abs": tolerance,
                **direction,
            },
        )

    def _run_batch_probe(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> Path | None:
        batch_command = list(context.bmt_manifest.plugin_config.get("batch_command", []))
        if not batch_command:
            return None
        results_relpath = str(context.bmt_manifest.plugin_config.get("batch_results_relpath", "")).strip()
        if not results_relpath:
            return None
        command = [
            part.format(
                runner=str(prepared_assets.runner_path or self._require_runner(context)),
                dataset=str(context.dataset_root),
                workspace=str(context.workspace_root),
            )
            for part in batch_command
        ]
        timeout_sec = _batch_command_timeout_sec()
        logs_root = context.logs_root
        logs_root.mkdir(parents=True, exist_ok=True)
        stdout_log = logs_root / "batch_probe.stdout.log"
        stderr_log = logs_root / "batch_probe.stderr.log"
        meta_log = logs_root / "batch_probe.meta.txt"
        try:
            proc = subprocess.run(
                command,
                cwd=str(context.workspace_root),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning("Batch runner timed out after %s s; command=%s", timeout_sec, command)
            meta_log.write_text(
                f"status=timeout\nseconds={timeout_sec}\ncommand={command!r}\n{exc}\n",
                encoding="utf-8",
            )
            stdout_log.write_text("", encoding="utf-8")
            stderr_log.write_text("", encoding="utf-8")
            return None
        stdout_log.write_text(proc.stdout or "", encoding="utf-8")
        stderr_log.write_text(proc.stderr or "", encoding="utf-8")
        meta_log.write_text(
            f"exit_code={proc.returncode}\ncommand={command!r}\ncwd={context.workspace_root}\n",
            encoding="utf-8",
        )
        if proc.returncode != 0:
            logger.warning(
                "Batch runner failed (exit %d); see %s and %s (full output on disk)",
                proc.returncode,
                stdout_log,
                stderr_log,
            )
            return None
        batch_path = _resolve_batch_results_file(context.workspace_root, results_relpath)
        if batch_path is None:
            logger.warning(
                "Batch completed but results file missing or not under workspace: %s",
                results_relpath,
            )
        return batch_path

    def _parse_batch_json(self, batch_path: Path, workspace_root: Path) -> ExecutionResult:
        """Batch JSON to ``ExecutionResult``; ``ValueError`` on bad path, I/O, JSON, or schema."""
        resolved = batch_path.resolve()
        base = workspace_root.resolve()
        if not resolved.is_relative_to(base):
            raise ValueError(f"Batch JSON path outside workspace: {batch_path}")
        try:
            raw = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Cannot read batch JSON: {batch_path}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in batch file {batch_path}") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"Batch JSON must be an object, got {type(payload).__name__}")
        try:
            batch = KardomeBatchFile.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"Invalid batch JSON in {batch_path}: {exc}") from exc
        case_results = [row.to_case_result() for row in batch.results]
        return ExecutionResult(
            execution_mode_used="kardome_batch_json",
            case_results=case_results,
            raw_summary=payload,
        )

    @staticmethod
    def _require_runner(context: ExecutionContext) -> Path:
        if context.runner_path is None:
            raise FileNotFoundError(f"Runner path is not configured for {context.bmt_manifest.bmt_slug}")
        return context.runner_path

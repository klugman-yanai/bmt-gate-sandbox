from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.config.bmt_domain_status import BmtLegStatus
from backend.runtime.kardome_batch_results import KardomeBatchFile
from backend.runtime.legacy_kardome import LegacyKardomeStdoutConfig, LegacyKardomeStdoutExecutor
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.kardome import AdaptiveKardomeExecutor
from backend.runtime.sdk.plugin import PLUGIN_EXECUTE_EXCEPTION_RAW_KEY, BmtPlugin
from backend.runtime.sdk.results import (
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from backend.runtime.sdk.subprocess_batch import run_subprocess_in_workspace
from backend.runtime.stdout_counter_parse import StdoutCounterParseConfig
from sk_plugin.sk_scoring_policy import (
    aggregate_mean_ok_cases,
    build_case_outcomes,
    scoring_policy_record,
)

logger = logging.getLogger(__name__)


class SkPlugin(BmtPlugin):
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
        return self.prepared_assets_from_context(context)

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        try:
            runner_env = self.runner_env_with_deps(context)
            validated_parse = self.parse_plugin_config(context, StdoutCounterParseConfig)
            legacy = LegacyKardomeStdoutExecutor(
                LegacyKardomeStdoutConfig(
                    runner_path=prepared_assets.runner_path or self.require_runner(context),
                    template_path=self.resolve_runner_template_path(context),
                    dataset_root=context.dataset_root,
                    runtime_root=context.workspace_root,
                    outputs_root=context.outputs_root,
                    logs_root=context.logs_root,
                    parsing=validated_parse.model_dump(mode="python", exclude_none=True),
                    enable_overrides=dict(context.bmt_manifest.plugin_config.get("enable_overrides", {})),
                    num_source_test=context.bmt_manifest.plugin_config.get("num_source_test"),
                    runner_env=runner_env,
                )
            )

            return AdaptiveKardomeExecutor(
                execution_policy=context.bmt_manifest.execution.policy,
                run_batch=lambda: self._run_batch_probe(context, prepared_assets),
                parse_batch=lambda p: self._parse_batch_json(p, context.workspace_root),
                run_legacy=legacy.run,
            ).run()
        except Exception as exc:
            return self.execution_failure_result(exc, prepared=prepared_assets, context=context)

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
        if execution_result.raw_summary.get(PLUGIN_EXECUTE_EXCEPTION_RAW_KEY) or execution_result.raw_summary.get(
            "sk_plugin_execute_exception"
        ):
            extra["plugin_execute_exception"] = True
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
        if score_result.extra.get("plugin_execute_exception") or score_result.extra.get("sk_plugin_execute_exception"):
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

        grace = self.max_grace_case_failures(context.bmt_manifest.plugin_config)
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
                    **direction,
                },
            )

        grace_meta: dict[str, Any] = {}
        if cases_failed > 0:
            grace_meta = {
                "max_grace_case_failures": grace,
                "grace_case_failures": cases_failed,
                "cases_failed_ids": failed_ids,
            }
            logger.warning(
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
                    **direction,
                    **grace_meta,
                },
            )
        if comparison == "lte":
            passed = score_result.aggregate_score <= baseline.aggregate_score + tolerance
        else:
            passed = score_result.aggregate_score >= baseline.aggregate_score - tolerance
        if not passed:
            return VerdictResult(
                passed=False,
                status=BmtLegStatus.FAIL.value,
                reason_code="score_outside_tolerance",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "baseline_score": baseline.aggregate_score,
                    "tolerance_abs": tolerance,
                    **direction,
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
                "tolerance_abs": tolerance,
                **direction,
                **grace_meta,
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
                runner=str(prepared_assets.runner_path or self.require_runner(context)),
                dataset=str(context.dataset_root),
                workspace=str(context.workspace_root),
            )
            for part in batch_command
        ]
        timeout_sec = self.batch_command_timeout_seconds()
        try:
            proc = run_subprocess_in_workspace(
                command,
                cwd=context.workspace_root,
                timeout_sec=timeout_sec,
                log=logger,
                label="batch",
            )
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            logger.warning(
                "Batch runner failed (exit %d); stdout: %s; stderr: %s",
                proc.returncode,
                proc.stdout[:2000],
                proc.stderr[:2000],
            )
            return None
        batch_path = self.resolve_workspace_file(context.workspace_root, results_relpath)
        if batch_path is None:
            logger.warning(
                "Batch completed but results file missing or not under workspace: %s",
                results_relpath,
            )
        return batch_path

    def _parse_batch_json(self, batch_path: Path, workspace_root: Path) -> ExecutionResult:
        """Parse batch JSON; raises ``ValueError`` on invalid path, I/O, JSON, or schema."""
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

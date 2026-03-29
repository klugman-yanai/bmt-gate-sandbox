from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from bmtplugin import (
    PLUGIN_EXECUTE_EXCEPTION_RAW_KEY,
    AdaptiveKardomeExecutor,
    BaselineToleranceEvaluator,
    BmtPlugin,
    CaseRunSummary,
    ExecutionContext,
    ExecutionMode,
    ExecutionResult,
    KardomeBatchFile,
    LegacyKardomeStdoutExecutor,
    PreparedAssets,
    ScoreResult,
    StdoutCounterParseConfig,
    VerdictResult,
    legacy_stdout_config_from_context,
    run_subprocess_in_workspace,
)
from pydantic import ValidationError

from .sk_scoring_policy import (
    aggregate_mean_ok_cases,
    build_case_outcomes,
    scoring_policy_record,
)

logger = logging.getLogger(__name__)

_SK_BASELINE_VERDICT = BaselineToleranceEvaluator(
    plugin_execute_extra_keys=("sk_plugin_execute_exception",),
)


class SkPlugin(BmtPlugin):
    plugin_name = "sk"
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
            legacy = LegacyKardomeStdoutExecutor(
                legacy_stdout_config_from_context(
                    self,
                    context,
                    prepared_assets,
                    parse_model=StdoutCounterParseConfig,
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
        summary = CaseRunSummary.from_case_results(execution_result.case_results)
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
        metrics = summary.as_score_metrics()
        metrics["case_outcomes"] = case_outcomes
        return ScoreResult(
            aggregate_score=aggregate,
            metrics=metrics,
            extra=extra,
        )

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        return _SK_BASELINE_VERDICT.evaluate(
            grace_policy=self,
            context=context,
            score_result=score_result,
            baseline=baseline,
            direction_fields=self._verdict_direction_fields(context),
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
            execution_mode_used=ExecutionMode.KARDOME_BATCH_JSON,
            case_results=case_results,
            raw_summary=payload,
        )

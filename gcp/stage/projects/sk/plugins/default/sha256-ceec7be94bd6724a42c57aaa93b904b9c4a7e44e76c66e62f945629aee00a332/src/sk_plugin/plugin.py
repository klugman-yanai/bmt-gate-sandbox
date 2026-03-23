from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from gcp.image.config.bmt_domain_status import BmtLegStatus
from gcp.image.runtime.legacy_kardome import LegacyKardomeStdoutConfig, LegacyKardomeStdoutExecutor
from gcp.image.runtime.sdk.context import ExecutionContext
from gcp.image.runtime.sdk.kardome import AdaptiveKardomeExecutor
from gcp.image.runtime.sdk.plugin import BmtPlugin
from gcp.image.runtime.sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)

logger = logging.getLogger(__name__)


class SkPlugin(BmtPlugin):
    plugin_name = "default"
    api_version = "v1"

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        return PreparedAssets(
            dataset_root=context.dataset_root,
            workspace_root=context.workspace_root,
            runner_path=context.runner_path,
        )

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        runner_env: dict[str, str] = {}
        if context.deps_root is not None and context.deps_root.is_dir():
            import os

            existing = os.environ.get("LD_LIBRARY_PATH", "").strip()
            runner_env["LD_LIBRARY_PATH"] = (
                f"{context.deps_root}:{existing}" if existing else str(context.deps_root)
            )
        legacy = LegacyKardomeStdoutExecutor(
            LegacyKardomeStdoutConfig(
                runner_path=prepared_assets.runner_path or self._require_runner(context),
                template_path=(Path.cwd() / context.bmt_manifest.runner.template_path).resolve(),
                dataset_root=context.dataset_root,
                runtime_root=context.workspace_root,
                outputs_root=context.outputs_root,
                logs_root=context.logs_root,
                parsing={
                    "keyword": context.bmt_manifest.plugin_config.get("keyword", "NAMUH"),
                    "counter_pattern": context.bmt_manifest.plugin_config.get(
                        "counter_pattern", r"Hi NAMUH counter = (\d+)"
                    ),
                },
                enable_overrides=dict(context.bmt_manifest.plugin_config.get("enable_overrides", {})),
                num_source_test=context.bmt_manifest.plugin_config.get("num_source_test"),
                runner_env=runner_env,
            )
        )

        return AdaptiveKardomeExecutor(
            execution_policy=context.bmt_manifest.execution.policy,
            run_batch=lambda: self._run_batch_probe(context, prepared_assets),
            parse_batch=self._parse_batch_json,
            run_legacy=legacy.run,
        ).run()

    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        values = [result.metrics.get("namuh_count", 0.0) for result in execution_result.case_results]
        aggregate = sum(float(value) for value in values) / len(values) if values else 0.0
        return ScoreResult(
            aggregate_score=aggregate,
            metrics={"case_count": len(values)},
            extra={"baseline_present": baseline is not None},
        )

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        comparison = str(context.bmt_manifest.plugin_config.get("comparison", "gte")).strip().lower()
        tolerance = float(context.bmt_manifest.plugin_config.get("tolerance_abs", 0.25) or 0.25)
        if baseline is None:
            return VerdictResult(
                passed=True,
                status=BmtLegStatus.PASS.value,
                reason_code="bootstrap_without_baseline",
                summary={
                    "aggregate_score": score_result.aggregate_score,
                    "comparison": comparison,
                    "baseline_score": None,
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
                "comparison": comparison,
                "tolerance_abs": tolerance,
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
        proc = subprocess.run(command, cwd=str(context.workspace_root), check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            logger.warning(
                "Batch runner failed (exit %d); stdout: %s; stderr: %s",
                proc.returncode,
                proc.stdout[:2000],
                proc.stderr[:2000],
            )
            return None
        batch_path = context.workspace_root / results_relpath
        return batch_path if batch_path.is_file() else None

    def _parse_batch_json(self, batch_path: Path) -> ExecutionResult:
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
        case_results: list[CaseResult] = []
        for item in payload.get("results", []):
            raw_status = item.get("status")
            raw_count = item.get("namuh_count")
            if raw_status is None or raw_count is None:
                raise ValueError(f"Batch result item missing required fields 'status' and/or 'namuh_count': {item}")
            case_results.append(
                CaseResult(
                    case_id=str(item.get("case_id") or item.get("file") or ""),
                    input_path=Path(str(item.get("file") or "")),
                    exit_code=int(item.get("exit_code", 0) or 0),
                    status=str(raw_status),
                    metrics={"namuh_count": float(raw_count)},
                    artifacts={},
                    error=str(item.get("error") or ""),
                )
            )
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

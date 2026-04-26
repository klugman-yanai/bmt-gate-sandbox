from __future__ import annotations

from bmt_sdk import BmtPlugin, ExecutionContext
from bmt_sdk.results import CaseResult, ExecutionResult, PreparedAssets, ScoreResult, VerdictResult

from runtime.config.bmt_domain_status import BmtLegStatus


class E2ETestPlugin(BmtPlugin):
    plugin_name = "e2e-test-plugin"

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        if not context.dataset_root.is_dir():
            raise FileNotFoundError(f"Dataset root not found: {context.dataset_root}")
        input_file = context.dataset_root / "test_input.txt"
        if not input_file.is_file():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        return PreparedAssets(
            dataset_root=context.dataset_root,
            workspace_root=context.workspace_root,
        )

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        del prepared_assets
        input_file = context.dataset_root / "test_input.txt"
        with input_file.open(encoding="utf-8") as handle:
            lines_read = len(handle.readlines())
        return ExecutionResult(
            execution_mode_used="e2e-test",
            case_results=[
                CaseResult(
                    case_id="test_input.txt",
                    input_path=input_file,
                    exit_code=0,
                    status="ok",
                    metrics={"lines_read": float(lines_read)},
                    artifacts={},
                    error="",
                )
            ],
            raw_summary={"status": "success", "lines_read": lines_read},
        )

    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        del baseline, context
        lines = float(execution_result.case_results[0].metrics.get("lines_read", 0.0))
        return ScoreResult(aggregate_score=lines, metrics={"lines_read": lines})

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        del baseline, context
        return VerdictResult(
            passed=True,
            status=BmtLegStatus.PASS.value,
            reason_code="e2e_test_passed",
            summary={"detail": "E2E test passed successfully."},
        )

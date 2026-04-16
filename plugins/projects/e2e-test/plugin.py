from __future__ import annotations

import json
from pathlib import Path

from bmt_sdk import BmtPlugin, ExecutionContext
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


class E2ETestPlugin(BmtPlugin):
    plugin_name = "e2e-test-plugin"

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        # In a real plugin, this might download files from GCS to local disk.
        # For this E2E test, we'll just ensure the dataset_root exists.
        if not context.dataset_root.is_dir():
            raise FileNotFoundError(f"Dataset root not found: {context.dataset_root}")
        # Simulate finding an input file
        input_file = context.dataset_root / "test_input.txt"
        if not input_file.is_file():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        return PreparedAssets(asset_paths=[input_file])

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        # Simulate running a process and generating some output.
        # In a real plugin, this would invoke an external runner like kardome_runner.
        # For this test, we'll just write a dummy result file.
        output_file = context.outputs_root / "execution_output.json"
        execution_data = {"lines_read": 0, "status": "success"}
        for asset_path in prepared_assets.asset_paths:
            if asset_path.name == "test_input.txt":
                with open(asset_path, "r") as f:
                    execution_data["lines_read"] = len(f.readlines())

        output_file.write_text(json.dumps(execution_data))
        return ExecutionResult(output_paths=[output_file], execution_mode_used="e2e-test")

    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        # Read the dummy result file and assign a score.
        output_file = execution_result.output_paths[0]
        execution_data = json.loads(output_file.read_text())
        score = execution_data["lines_read"]
        return ScoreResult(aggregate_score=float(score), metrics=execution_data)

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        # Always pass for this simple test
        return VerdictResult(status="PASS", reason_code="e2e_test_passed", summary="E2E test passed successfully.")

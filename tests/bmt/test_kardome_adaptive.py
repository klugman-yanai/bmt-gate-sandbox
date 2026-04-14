from __future__ import annotations

from pathlib import Path

import pytest
from bmt_sdk.results import CaseResult, ExecutionResult

from runtime.kardome import AdaptiveKardomeExecutor

pytestmark = pytest.mark.integration


def test_adaptive_kardome_falls_back_to_legacy_when_batch_result_missing(tmp_path: Path) -> None:
    calls: list[str] = []

    def run_batch() -> Path | None:
        calls.append("batch")
        return None

    def parse_batch(_path: Path) -> ExecutionResult:
        raise AssertionError("batch parser should not be called")

    def run_legacy() -> ExecutionResult:
        calls.append("legacy")
        return ExecutionResult(
            execution_mode_used="kardome_legacy_stdout",
            case_results=[
                CaseResult(
                    case_id="sample.wav",
                    input_path=tmp_path / "sample.wav",
                    exit_code=0,
                    status="ok",
                    metrics={"score": 1.0},
                )
            ],
        )

    result = AdaptiveKardomeExecutor(
        execution_policy="adaptive_batch_then_legacy",
        run_batch=run_batch,
        parse_batch=parse_batch,
        run_legacy=run_legacy,
    ).run()

    assert calls == ["batch", "legacy"]
    assert result.execution_mode_used == "kardome_legacy_stdout"

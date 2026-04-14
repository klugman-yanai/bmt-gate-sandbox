"""Helpers for adaptive kardome execution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gcp.image.runtime.sdk.results import ExecutionResult


class AdaptiveKardomeExecutor:
    """Try future batch-json flow first, then fall back to legacy execution."""

    def __init__(
        self,
        *,
        execution_policy: str,
        run_batch: Callable[[], Path | None],
        parse_batch: Callable[[Path], ExecutionResult],
        run_legacy: Callable[[], ExecutionResult],
    ) -> None:
        self.execution_policy = execution_policy
        self.run_batch = run_batch
        self.parse_batch = parse_batch
        self.run_legacy = run_legacy

    def run(self) -> ExecutionResult:
        if self.execution_policy not in {"adaptive_batch_then_legacy", "batch_json_only", "legacy_only"}:
            raise ValueError(f"Unsupported execution policy: {self.execution_policy}")

        if self.execution_policy != "legacy_only":
            batch_path = self.run_batch()
            if batch_path is not None and batch_path.is_file():
                return self.parse_batch(batch_path)
            if self.execution_policy == "batch_json_only":
                raise FileNotFoundError("Batch JSON results were required but not produced")

        return self.run_legacy()

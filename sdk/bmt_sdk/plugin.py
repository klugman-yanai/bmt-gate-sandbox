"""Contributor plugin contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


class BmtPlugin(ABC):
    """Stable BMT plugin contract.

    Subclass this and implement all four methods. Drop your subclass in
    ``plugins/<project>/plugin.py`` — the runtime discovers it automatically.
    """

    plugin_name = "default"
    api_version = "v1"

    @abstractmethod
    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        """Resolve assets needed before execution."""

    @abstractmethod
    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        """Run a BMT leg and return normalized results."""

    @abstractmethod
    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        """Convert normalized execution output into a score."""

    @abstractmethod
    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        """Return pass/fail semantics for the score."""

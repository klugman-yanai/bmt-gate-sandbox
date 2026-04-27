"""Contributor plugin contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from bmt_sdk.context import ExecutionContext
from bmt_sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


class BmtPlugin(ABC):
    """Implement in ``plugins/<project>/plugin.py``; runtime loads it automatically.

    Call order: :meth:`prepare` → :meth:`execute` → :meth:`score` → :meth:`evaluate`.
    """

    plugin_name = "default"
    api_version = "v1"

    @abstractmethod
    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        """Paths and tools before :meth:`execute` (keep it light)."""

    @abstractmethod
    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        """One :class:`CaseResult` per input; ``status="failed"`` for runner or parse errors."""

    @abstractmethod
    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        """Counters in ``metrics``; policy and check-run copy in ``extra``."""

    @abstractmethod
    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        """Stable machine ``reason_code``; reporting turns that into check text."""

"""Structural typing for plugins (tests, fakes) without inheriting :class:`BmtPlugin`."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.runtime.models import PluginManifest
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


@runtime_checkable
class BmtPluginProtocol(Protocol):
    """Mirror of the :class:`~backend.runtime.sdk.plugin.BmtPlugin` lifecycle for type checkers."""

    plugin_name: str
    api_version: str

    def prepare(self, context: ExecutionContext) -> PreparedAssets: ...

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult: ...

    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult: ...

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult: ...

    def teardown(self, context: ExecutionContext, prepared: PreparedAssets) -> None: ...

    def validate_against_loaded_manifest(self, manifest: PluginManifest) -> None: ...

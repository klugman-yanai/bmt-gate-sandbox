"""Structural typing for plugins, fakes, and gating collaborators.

`PEP 544`_ runtime-checkable protocols let tests provide lightweight doubles without
subclassing :class:`~backend.runtime.sdk.plugin.BmtPlugin`.

.. _PEP 544: https://peps.python.org/pep-0544/
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.runtime.models import PluginManifest
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.results import ExecutionResult, PreparedAssets, ScoreResult, VerdictResult


@runtime_checkable
class SupportsGraceCaseLimits(Protocol):
    """Object that supplies how many failed cases are tolerated before hard-failing a leg."""

    def max_grace_case_failures(self, plugin_config: dict[str, Any]) -> int:
        """Return a non-negative cap; typically reads ``plugin_config['max_grace_case_failures']``."""
        ...


@runtime_checkable
class BmtPluginProtocol(SupportsGraceCaseLimits, Protocol):
    """Full lifecycle surface expected by the runtime and coordinator (structural subtype of :class:`BmtPlugin`)."""

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

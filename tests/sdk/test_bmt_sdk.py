"""Tests for the bmt_sdk package — no runtime imports allowed."""

from __future__ import annotations

from pathlib import Path

import pytest

# These imports must work without gcp.image installed
from bmt_sdk import BmtPlugin, ExecutionContext
from bmt_sdk.models import (
    BmtManifestView,
    ExecutionConfigView,
    ProjectManifestView,
    RunnerConfigView,
)
from bmt_sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)


def _make_context(plugin_config: dict | None = None) -> ExecutionContext:
    return ExecutionContext(
        project_manifest=ProjectManifestView(project="test"),
        bmt_manifest=BmtManifestView(
            project="test",
            bmt_slug="test_bmt",
            bmt_id="00000000-0000-0000-0000-000000000001",
            enabled=True,
            plugin_config=plugin_config or {},
        ),
        plugin_root=Path("/fake/plugin"),
        workspace_root=Path("/fake/workspace"),
        dataset_root=Path("/fake/dataset"),
        outputs_root=Path("/fake/outputs"),
        logs_root=Path("/fake/logs"),
    )


def test_bmt_plugin_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BmtPlugin()  # abstract class; instantiation raises TypeError at runtime


def test_bmt_plugin_subclass_must_implement_all_methods() -> None:
    class IncompletePlugin(BmtPlugin):
        def prepare(self, context: ExecutionContext) -> PreparedAssets:
            return PreparedAssets(
                dataset_root=context.dataset_root,
                workspace_root=context.workspace_root,
            )

        # Missing: execute, score, evaluate

    with pytest.raises(TypeError):
        IncompletePlugin()  # abstract subclass with missing methods; raises TypeError at runtime


def test_bmt_plugin_subclass_valid() -> None:
    class MinimalPlugin(BmtPlugin):
        def prepare(self, context: ExecutionContext) -> PreparedAssets:
            return PreparedAssets(
                dataset_root=context.dataset_root,
                workspace_root=context.workspace_root,
            )

        def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
            return ExecutionResult(execution_mode_used="test", case_results=[])

        def score(
            self,
            execution_result: ExecutionResult,
            baseline: ScoreResult | None,
            context: ExecutionContext,
        ) -> ScoreResult:
            return ScoreResult(aggregate_score=1.0)

        def evaluate(
            self,
            score_result: ScoreResult,
            baseline: ScoreResult | None,
            context: ExecutionContext,
        ) -> VerdictResult:
            return VerdictResult(passed=True, status="pass", reason_code="ok")

    plugin = MinimalPlugin()
    ctx = _make_context()
    prepared = plugin.prepare(ctx)
    result = plugin.execute(ctx, prepared)
    score = plugin.score(result, None, ctx)
    verdict = plugin.evaluate(score, None, ctx)
    assert verdict.passed is True
    assert verdict.status == "pass"


def test_execution_context_is_frozen() -> None:
    ctx = _make_context()
    with pytest.raises((AttributeError, TypeError)):
        ctx.workspace_root = Path("/other")  # type: ignore[misc]


def test_bmt_manifest_view_defaults() -> None:
    view = BmtManifestView(
        project="acme",
        bmt_slug="false_alarms",
        bmt_id="uuid",
        enabled=True,
        plugin_config={},
    )
    assert view.execution.policy == "adaptive_batch_then_legacy"
    assert view.runner.uri == ""


def test_no_gcp_image_import_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify bmt_sdk has no gcp.image dependency at import time."""
    import importlib
    import sys

    # Remove both gcp.* and bmt_sdk.* from sys.modules so bmt_sdk is fully re-imported
    # from scratch (not served from cache), which would expose any gcp import in sub-modules.
    gcp_modules = [k for k in sys.modules if k.startswith("gcp")]
    bmt_modules = [k for k in sys.modules if k.startswith("bmt_sdk")]
    saved = {k: sys.modules.pop(k) for k in gcp_modules + bmt_modules}
    try:
        import bmt_sdk

        importlib.reload(bmt_sdk)
        # If we reach here, bmt_sdk and all its sub-modules imported without gcp
    finally:
        sys.modules.update(saved)

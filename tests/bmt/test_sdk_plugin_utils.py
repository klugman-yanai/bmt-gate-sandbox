"""Tests for contributor-facing SDK helpers (stage layout, case summary, verdicts, Kardome glue)."""

from __future__ import annotations

from pathlib import Path

import pytest
from backend.config.value_types import as_results_path
from backend.runtime.models import BmtManifest, ProjectManifest, RunnerConfig
from backend.runtime.sdk import contributor
from backend.runtime.sdk.baseline_verdict import (
    evaluate_baseline_tolerance_verdict,
    evaluate_pass_threshold_verdict,
)
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.kardome_stdout import legacy_stdout_config_from_context
from backend.runtime.sdk.plugin import BmtPlugin
from backend.runtime.sdk.protocols import SupportsGraceCaseLimits
from backend.runtime.sdk.results import (
    CaseArtifacts,
    CaseMetrics,
    CaseResult,
    CaseRunSummary,
    CaseStatus,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from backend.runtime.sdk.stage_layout import (
    SHARED_DEPENDENCIES_PREFIX,
    native_runner_uri,
    resolve_posix_under_stage,
    runner_config_native_kardome,
    shared_dependencies_dir,
)
from backend.runtime.stdout_counter_parse import StdoutCounterParseConfig

from tests.support.fixtures.bmt_sdk import minimal_execution_context

pytestmark = pytest.mark.unit


def test_contributor_module_reexports_core_api() -> None:
    """``sdk.contributor`` is the single import surface for plugin authors."""
    assert contributor.BmtPlugin is not None
    assert contributor.ExecutionContext is not None
    assert contributor.CaseRunSummary is not None
    assert contributor.PassThresholdEvaluator is not None
    assert contributor.BaselineToleranceEvaluator is not None
    assert contributor.SupportsGraceCaseLimits is not None
    assert contributor.evaluate_pass_threshold_verdict is not None
    assert contributor.legacy_stdout_config_from_context is not None
    assert "BmtPlugin" in contributor.__all__


def test_shared_dependencies_dir_and_runner_uri() -> None:
    root = Path("/tmp/stage")
    assert shared_dependencies_dir(root) == root / "projects" / "shared" / "dependencies"
    assert native_runner_uri("sk") == "projects/sk/lib/kardome_runner"
    rc = runner_config_native_kardome("sk")
    assert rc.uri == "projects/sk/lib/kardome_runner"
    assert rc.deps_prefix == SHARED_DEPENDENCIES_PREFIX
    assert "runner_input.template" in rc.template_path


def test_resolve_posix_under_stage() -> None:
    stage = Path("/b")
    assert resolve_posix_under_stage(stage, "projects/p/x") == stage / "projects" / "p" / "x"
    assert resolve_posix_under_stage(stage, "") == stage


def test_case_run_summary() -> None:
    cases = [
        CaseResult(
            case_id="a",
            input_path=Path("a.wav"),
            exit_code=0,
            status=CaseStatus.OK,
            metrics=CaseMetrics(root={}),
            artifacts=CaseArtifacts(root={}),
        ),
        CaseResult(
            case_id="b",
            input_path=Path("b.wav"),
            exit_code=1,
            status=CaseStatus.FAILED,
            metrics=CaseMetrics(root={}),
            artifacts=CaseArtifacts(root={}),
        ),
    ]
    s = CaseRunSummary.from_case_results(cases)
    assert s.case_count == 2 and s.cases_ok == 1 and s.cases_failed == 1
    m = s.as_score_metrics()
    assert m["cases_failed_ids"] == ["b"]


class _StubPlugin(BmtPlugin):
    plugin_name = "stub"
    api_version = "v1"

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        raise NotImplementedError

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        raise NotImplementedError

    def score(
        self,
        execution_result: ExecutionResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> ScoreResult:
        raise NotImplementedError

    def evaluate(
        self,
        score_result: ScoreResult,
        baseline: ScoreResult | None,
        context: ExecutionContext,
    ) -> VerdictResult:
        raise NotImplementedError


def test_bmt_plugin_instances_support_grace_protocol() -> None:
    """Runtime-checkable :class:`SupportsGraceCaseLimits` matches concrete plugins."""
    assert isinstance(_StubPlugin(), SupportsGraceCaseLimits)


def test_evaluate_pass_threshold_verdict(tmp_path: Path) -> None:
    ctx = minimal_execution_context(tmp_path)
    ctx.bmt_manifest.plugin_config["pass_threshold"] = 1.0
    sr = ScoreResult(aggregate_score=2.0, metrics={}, extra={})
    v = evaluate_pass_threshold_verdict(sr, ctx)
    assert v.passed is True

    sr2 = ScoreResult(aggregate_score=0.5, metrics={}, extra={})
    v2 = evaluate_pass_threshold_verdict(sr2, ctx)
    assert v2.passed is False


def test_evaluate_baseline_tolerance_bootstrap(tmp_path: Path) -> None:
    ctx = minimal_execution_context(tmp_path)
    ctx.bmt_manifest.plugin_config.update({"comparison": "gte", "tolerance_abs": 0.25})
    plugin = _StubPlugin()
    sr = ScoreResult(
        aggregate_score=1.0,
        metrics=CaseRunSummary.from_case_results(
            [
                CaseResult(
                    case_id="x",
                    input_path=Path("x.wav"),
                    exit_code=0,
                    status=CaseStatus.OK,
                    metrics=CaseMetrics(root={}),
                    artifacts=CaseArtifacts(root={}),
                )
            ]
        ).as_score_metrics(),
        extra={},
    )
    v = evaluate_baseline_tolerance_verdict(
        plugin=plugin,
        context=ctx,
        score_result=sr,
        baseline=None,
        direction_fields={},
    )
    assert v.passed and v.reason_code == "bootstrap_without_baseline"


def test_evaluate_baseline_tolerance_no_cases(tmp_path: Path) -> None:
    pm = ProjectManifest(project="p", default_plugin="main")
    bm = BmtManifest(
        project="p",
        bmt_slug="b",
        bmt_id="id",
        plugin_ref="workspace:main",
        inputs_prefix="projects/p/inputs/b",
        results_path=as_results_path("projects/p/results/b"),
        outputs_prefix="projects/p/outputs/b",
        runner=RunnerConfig(),
        plugin_config={},
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = ExecutionContext(
        project_manifest=pm,
        bmt_manifest=bm,
        plugin_root=tmp_path / "pl",
        workspace_root=ws,
        dataset_root=tmp_path / "ds",
        outputs_root=tmp_path / "out",
        logs_root=tmp_path / "logs",
    )
    for d in (ctx.dataset_root, ctx.outputs_root, ctx.logs_root):
        d.mkdir(exist_ok=True)
    sr = ScoreResult(aggregate_score=0.0, metrics={"case_count": 0}, extra={})
    v = evaluate_baseline_tolerance_verdict(
        plugin=_StubPlugin(),
        context=ctx,
        score_result=sr,
        baseline=None,
        direction_fields={},
    )
    assert not v.passed and v.reason_code == "no_dataset_cases"


def test_legacy_stdout_config_from_context(tmp_path: Path) -> None:
    ctx = minimal_execution_context(tmp_path)
    ctx.bmt_manifest.plugin_config["enable_overrides"] = {"KWS_CONFIG.KWS_ENABLE": True}
    prepared = PreparedAssets(
        dataset_root=ctx.dataset_root,
        workspace_root=ctx.workspace_root,
        runner_path=ctx.runner_path,
    )
    plugin = _StubPlugin()
    cfg = legacy_stdout_config_from_context(
        plugin,
        ctx,
        prepared,
        parse_model=StdoutCounterParseConfig,
    )
    assert cfg.dataset_root == ctx.dataset_root
    assert cfg.runner_path == ctx.runner_path
    assert cfg.enable_overrides == {"KWS_CONFIG.KWS_ENABLE": True}
    assert "LD_LIBRARY_PATH" not in cfg.runner_env  # no deps_root in minimal context

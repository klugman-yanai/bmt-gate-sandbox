from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from runtime.execution import execute_leg
from runtime.models import StageRuntimePaths, WorkflowRequest
from runtime.planning import PlanOptions, build_plan

pytestmark = pytest.mark.integration


def _setup_flat_project(stage_root: Path, project: str, bmt_slug: str) -> None:
    """Set up a flat-layout project with plugin.py at project root and a flat BMT manifest."""
    project_dir = stage_root / "projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps({"schema_version": 1, "project": project}, indent=2) + "\n",
        encoding="utf-8",
    )
    bmt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://bmt/{project}/{bmt_slug}"))
    (project_dir / f"{bmt_slug}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": project,
                "bmt_slug": bmt_slug,
                "bmt_id": bmt_id,
                "enabled": True,
                "plugin_ref": "direct",
                "inputs_prefix": f"projects/{project}/inputs/{bmt_slug}",
                "results_prefix": f"projects/{project}/results/{bmt_slug}",
                "outputs_prefix": f"projects/{project}/outputs/{bmt_slug}",
                "runner": {"uri": "", "deps_prefix": "", "template_path": "runtime/assets/kardome_input_template.json"},
                "execution": {"policy": "adaptive_batch_then_legacy"},
                "plugin_config": {"pass_threshold": 1.0},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    class_name = f"{project.capitalize()}Plugin"
    (project_dir / "plugin.py").write_text(
        f"""from __future__ import annotations
from bmt_sdk import BmtPlugin, ExecutionContext
from bmt_sdk.results import CaseResult, ExecutionResult, PreparedAssets, ScoreResult, VerdictResult
from runtime.config.bmt_domain_status import BmtLegStatus


class {class_name}(BmtPlugin):
    plugin_name = "default"
    api_version = "v1"

    def prepare(self, context: ExecutionContext) -> PreparedAssets:
        return PreparedAssets(
            dataset_root=context.dataset_root,
            workspace_root=context.workspace_root,
            runner_path=context.runner_path,
        )

    def execute(self, context: ExecutionContext, prepared_assets: PreparedAssets) -> ExecutionResult:
        case_results: list[CaseResult] = []
        for wav_path in sorted(context.dataset_root.rglob("*.wav")):
            rel = wav_path.relative_to(context.dataset_root).as_posix()
            case_results.append(
                CaseResult(case_id=rel, input_path=wav_path, exit_code=0, status="ok", metrics={{"score": 1.0}})
            )
        return ExecutionResult(execution_mode_used="plugin_direct", case_results=case_results)

    def score(self, execution_result: ExecutionResult, baseline: ScoreResult | None, context: ExecutionContext) -> ScoreResult:
        aggregate = 1.0 if execution_result.case_results else 0.0
        return ScoreResult(aggregate_score=aggregate, metrics={{"case_count": len(execution_result.case_results)}}, extra={{"baseline_present": baseline is not None}})

    def evaluate(self, score_result: ScoreResult, baseline: ScoreResult | None, context: ExecutionContext) -> VerdictResult:
        passed = score_result.aggregate_score >= 1.0
        return VerdictResult(
            passed=passed,
            status=BmtLegStatus.PASS.value if passed else BmtLegStatus.FAIL.value,
            reason_code="score_above_threshold" if passed else "score_below_threshold",
            summary={{"aggregate_score": score_result.aggregate_score}},
        )
""",
        encoding="utf-8",
    )


def test_planner_discovers_enabled_bmt_and_executor_runs_plugin(tmp_path: Path) -> None:
    """Flat-layout: planner discovers enabled BMT and executor loads plugin directly."""
    stage_root = tmp_path / "gcp" / "stage"
    workspace_root = tmp_path / "workspace"
    _setup_flat_project(stage_root, "acme", "wake_word_quality")

    dataset_root = stage_root / "projects" / "acme" / "inputs" / "wake_word_quality"
    dataset_root.mkdir(parents=True, exist_ok=True)
    (dataset_root / "sample.wav").write_bytes(b"fake")

    plan = build_plan(
        runtime=StageRuntimePaths(stage_root=stage_root, workspace_root=workspace_root),
        options=PlanOptions(
            request=WorkflowRequest(workflow_run_id="wf-123", accepted_projects=["acme"]),
            allow_workspace_plugins=False,
        ),
    )

    assert len(plan.legs) == 1
    assert plan.legs[0].plugin_ref == "direct"

    summary = execute_leg(
        plan=plan,
        leg=plan.legs[0],
        runtime=StageRuntimePaths(stage_root=stage_root, workspace_root=workspace_root),
    )

    assert summary.project == "acme"
    assert summary.bmt_slug == "wake_word_quality"
    assert summary.status == "pass"
    assert summary.execution_mode_used == "plugin_direct"
    assert summary.score.aggregate_score == 1.0

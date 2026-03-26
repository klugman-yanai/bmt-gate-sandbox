from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.runtime.execution import execute_leg
from backend.runtime.models import StageRuntimePaths, WorkflowRequest
from backend.runtime.planning import PlanOptions, build_plan
from backend.runtime.plugin_loader import WorkspacePluginRefError
from tools.bmt.publisher import publish_bmt
from tools.bmt.scaffold import add_bmt, add_project

pytestmark = pytest.mark.integration


def test_planner_discovers_enabled_bmt_and_executor_runs_plugin(tmp_path: Path) -> None:
    stage_root = tmp_path / "benchmarks"
    workspace_root = tmp_path / "workspace"
    add_project("acme", stage_root=stage_root, dry_run=False)
    add_bmt("acme", "wake_word_quality", stage_root=stage_root, plugin="default")

    manifest_path = stage_root / "projects" / "acme" / "bmts" / "wake_word_quality" / "bmt.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["enabled"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    dataset_root = stage_root / "projects" / "acme" / "inputs" / "wake_word_quality"
    dataset_root.mkdir(parents=True, exist_ok=True)
    (dataset_root / "sample.wav").write_bytes(b"fake")

    publish_result = publish_bmt(stage_root=stage_root, project="acme", bmt_slug="wake_word_quality", sync=False)

    plan = build_plan(
        runtime=StageRuntimePaths(stage_root=stage_root, workspace_root=workspace_root),
        options=PlanOptions(
            request=WorkflowRequest(workflow_run_id="wf-123", accepted_projects=["acme"]),
            allow_workspace_plugins=False,
        ),
    )

    assert len(plan.legs) == 1
    assert plan.legs[0].plugin_ref == publish_result.plugin_ref

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


def test_planner_rejects_workspace_plugins_in_production_mode(tmp_path: Path) -> None:
    stage_root = tmp_path / "benchmarks"
    workspace_root = tmp_path / "workspace"
    add_project("acme", stage_root=stage_root, dry_run=False)
    add_bmt("acme", "wake_word_quality", stage_root=stage_root, plugin="default")

    manifest_path = stage_root / "projects" / "acme" / "bmts" / "wake_word_quality" / "bmt.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["enabled"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(WorkspacePluginRefError, match="Workspace plugin refs"):
        build_plan(
            runtime=StageRuntimePaths(stage_root=stage_root, workspace_root=workspace_root),
            options=PlanOptions(
                request=WorkflowRequest(workflow_run_id="wf-123", accepted_projects=["acme"]),
                allow_workspace_plugins=False,
            ),
        )

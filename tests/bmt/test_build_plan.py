"""Tests for build_plan() uniqueness validation."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from gcp.image.runtime.models import StageRuntimePaths, WorkflowRequest
from gcp.image.runtime.planning import PlanOptions, build_plan

pytestmark = pytest.mark.unit


def _write_manifest(path: Path, project: str, bmt_slug: str, results_prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "project": project,
            "bmt_slug": bmt_slug,
            "bmt_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"bmt/{project}/{bmt_slug}")),
            "enabled": True,
            "plugin_ref": "published:default:sha256-deadbeef",
            "inputs_prefix": f"projects/{project}/inputs/{bmt_slug}",
            "results_prefix": results_prefix,
            "outputs_prefix": f"projects/{project}/outputs/{bmt_slug}",
        }) + "\n",
        encoding="utf-8",
    )


def _write_project_manifest(path: Path, project: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "project": project}) + "\n",
        encoding="utf-8",
    )


def _runtime(stage_root: Path, tmp_path: Path) -> StageRuntimePaths:
    return StageRuntimePaths(stage_root=stage_root, workspace_root=tmp_path / "workspace")


def test_build_plan_raises_on_duplicate_results_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_root = tmp_path / "stage"
    _write_project_manifest(stage_root / "projects" / "acme" / "project.json", "acme")
    _write_manifest(
        stage_root / "projects" / "acme" / "bmts" / "bmt_a" / "bmt.json",
        "acme", "bmt_a", "projects/acme/results/shared",
    )
    _write_manifest(
        stage_root / "projects" / "acme" / "bmts" / "bmt_b" / "bmt.json",
        "acme", "bmt_b", "projects/acme/results/shared",
    )
    monkeypatch.setattr(
        "gcp.image.runtime.planning._resolve_plugin_root",
        lambda *a, **kw: tmp_path / "fake_plugin",
    )
    monkeypatch.setattr(
        "gcp.image.runtime.planning.plugin_digest",
        lambda path: "fake-digest",
    )

    with pytest.raises(ValueError, match="results_path"):
        build_plan(
            runtime=_runtime(stage_root, tmp_path),
            options=PlanOptions(request=WorkflowRequest(workflow_run_id="wf-test")),
        )


def test_build_plan_accepts_unique_results_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage_root = tmp_path / "stage"
    _write_project_manifest(stage_root / "projects" / "acme" / "project.json", "acme")
    _write_manifest(
        stage_root / "projects" / "acme" / "bmts" / "bmt_a" / "bmt.json",
        "acme", "bmt_a", "projects/acme/results/bmt_a",
    )
    _write_manifest(
        stage_root / "projects" / "acme" / "bmts" / "bmt_b" / "bmt.json",
        "acme", "bmt_b", "projects/acme/results/bmt_b",
    )
    monkeypatch.setattr(
        "gcp.image.runtime.planning._resolve_plugin_root",
        lambda *a, **kw: tmp_path / "fake_plugin",
    )
    monkeypatch.setattr(
        "gcp.image.runtime.planning.plugin_digest",
        lambda path: "fake-digest",
    )

    plan = build_plan(
        runtime=_runtime(stage_root, tmp_path),
        options=PlanOptions(request=WorkflowRequest(workflow_run_id="wf-test")),
    )
    assert len(plan.legs) == 2

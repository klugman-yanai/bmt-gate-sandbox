"""Build immutable execution plans from staged manifests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from gcp.image.runtime.models import (
    BmtManifest,
    ExecutionPlan,
    PlanLeg,
    ProjectManifest,
    StageRuntimePaths,
    WorkflowRequest,
)
from gcp.image.runtime.plugin_loader import _resolve_plugin_root
from gcp.image.runtime.plugin_publisher import plugin_digest


@dataclass(frozen=True, slots=True)
class PlanOptions:
    request: WorkflowRequest
    allow_workspace_plugins: bool = False


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_plan(*, runtime: StageRuntimePaths, options: PlanOptions) -> ExecutionPlan:
    legs: list[PlanLeg] = []
    projects_root = runtime.stage_root / "projects"
    accepted_projects = {project for project in options.request.accepted_projects if project}
    for manifest_path in sorted(projects_root.glob("*/bmts/*/bmt.json")):
        bmt_manifest = BmtManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
        if not bmt_manifest.enabled:
            continue
        if accepted_projects and bmt_manifest.project not in accepted_projects:
            continue
        project_manifest_path = projects_root / bmt_manifest.project / "project.json"
        _ = ProjectManifest.model_validate(json.loads(project_manifest_path.read_text(encoding="utf-8")))
        plugin_root = _resolve_plugin_root(
            runtime.stage_root,
            bmt_manifest.project,
            bmt_manifest.plugin_ref,
            allow_workspace=options.allow_workspace_plugins,
        )
        run_id = f"{options.request.workflow_run_id}-{bmt_manifest.bmt_slug}"
        legs.append(
            PlanLeg(
                project=bmt_manifest.project,
                bmt_slug=bmt_manifest.bmt_slug,
                bmt_id=bmt_manifest.bmt_id,
                run_id=run_id,
                execution_profile=bmt_manifest.execution.profile,
                manifest_path=str(manifest_path.relative_to(runtime.stage_root)),
                manifest_digest=_file_digest(manifest_path),
                plugin_ref=bmt_manifest.plugin_ref,
                plugin_digest=plugin_digest(plugin_root),
                inputs_prefix=bmt_manifest.inputs_prefix,
                results_path=bmt_manifest.results_path,
                outputs_prefix=bmt_manifest.outputs_prefix,
            )
        )
    seen_results_paths: dict[str, str] = {}
    for leg in legs:
        key = str(leg.results_path)
        if key in seen_results_paths:
            raise ValueError(
                f"Duplicate results_path {key!r}: legs {seen_results_paths[key]!r} and "
                f"{leg.project!r}/{leg.bmt_slug!r} both write to the same path. "
                "Each enabled BMT must have a unique results_path."
            )
        seen_results_paths[key] = f"{leg.project}/{leg.bmt_slug}"
    standard_task_count = sum(1 for leg in legs if leg.execution_profile == "standard")
    heavy_task_count = sum(1 for leg in legs if leg.execution_profile == "heavy")
    return ExecutionPlan(
        workflow_run_id=options.request.workflow_run_id,
        repository=options.request.repository,
        head_sha=options.request.head_sha,
        head_branch=options.request.head_branch,
        head_event=options.request.head_event,
        pr_number=options.request.pr_number,
        run_context=options.request.run_context,
        accepted_projects=sorted(accepted_projects),
        status_context=options.request.status_context,
        use_mock_runner=options.request.use_mock_runner,
        standard_task_count=standard_task_count,
        heavy_task_count=heavy_task_count,
        legs=legs,
    )

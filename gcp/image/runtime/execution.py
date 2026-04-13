"""Execute a planned leg using the new plugin contract."""

from __future__ import annotations

import json

from bmt_sdk.context import ExecutionContext
from bmt_sdk.models import (
    BmtManifestView,
    ExecutionConfigView,
    ProjectManifestView,
    RunnerConfigView,
)

from gcp.image.config.bmt_domain_status import BmtLegStatus
from gcp.image.runtime.models import (
    BmtManifest,
    ExecutionPlan,
    LegSummary,
    PlanLeg,
    ProjectManifest,
    ScorePayload,
    StageRuntimePaths,
)
from gcp.image.runtime.plugin_loader import load_plugin


def _make_manifest_view(m: BmtManifest) -> BmtManifestView:
    return BmtManifestView(
        project=m.project,
        bmt_slug=m.bmt_slug,
        bmt_id=m.bmt_id,
        enabled=m.enabled,
        plugin_config=dict(m.plugin_config),
        inputs_prefix=m.inputs_prefix,
        results_prefix=str(m.results_path),
        outputs_prefix=m.outputs_prefix,
        execution=ExecutionConfigView(
            policy=m.execution.policy,
            profile=m.execution.profile,
        ),
        runner=RunnerConfigView(
            uri=m.runner.uri,
            deps_prefix=m.runner.deps_prefix,
            template_path=m.runner.template_path,
        ),
    )


def _make_project_view(p: ProjectManifest) -> ProjectManifestView:
    return ProjectManifestView(
        project=p.project,
        description=p.description,
    )


def execute_leg(*, plan: ExecutionPlan, leg: PlanLeg, runtime: StageRuntimePaths) -> LegSummary:
    use_mock = plan.use_mock_runner
    del plan
    if use_mock:
        return LegSummary(
            project=leg.project,
            bmt_slug=leg.bmt_slug,
            bmt_id=leg.bmt_id,
            run_id=leg.run_id,
            status=BmtLegStatus.PASS.value,
            reason_code="bootstrap_without_baseline",
            plugin_ref=leg.plugin_ref,
            execution_mode_used="mock",
            score=ScorePayload(aggregate_score=0.0),
        )
    manifest_path = runtime.stage_root / leg.manifest_path
    bmt_manifest = BmtManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    project_manifest_path = runtime.stage_root / "projects" / leg.project / "project.json"
    project_manifest = ProjectManifest.model_validate(json.loads(project_manifest_path.read_text(encoding="utf-8")))
    plugin, plugin_root = load_plugin(
        runtime.stage_root,
        leg.project,
        bmt_manifest.plugin_ref,
        allow_workspace=False,
    )

    run_root = runtime.workspace_root / leg.project / leg.bmt_slug / leg.run_id
    outputs_root = run_root / "outputs"
    logs_root = run_root / "logs"
    outputs_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    deps_prefix = bmt_manifest.runner.deps_prefix.strip()
    context = ExecutionContext(
        project_manifest=_make_project_view(project_manifest),
        bmt_manifest=_make_manifest_view(bmt_manifest),
        plugin_root=plugin_root,
        workspace_root=run_root,
        dataset_root=runtime.stage_root / bmt_manifest.inputs_prefix,
        outputs_root=outputs_root,
        logs_root=logs_root,
        runner_path=(runtime.stage_root / bmt_manifest.runner.uri) if bmt_manifest.runner.uri else None,
        deps_root=(runtime.stage_root / deps_prefix) if deps_prefix else None,
    )
    prepared = plugin.prepare(context)
    execution_result = plugin.execute(context, prepared)
    score = plugin.score(execution_result, None, context)
    verdict = plugin.evaluate(score, None, context)

    return LegSummary(
        project=leg.project,
        bmt_slug=leg.bmt_slug,
        bmt_id=leg.bmt_id,
        run_id=leg.run_id,
        status=verdict.status,
        reason_code=verdict.reason_code,
        plugin_ref=leg.plugin_ref,
        execution_mode_used=execution_result.execution_mode_used,
        score=ScorePayload(
            aggregate_score=score.aggregate_score,
            metrics=score.metrics,
            extra=score.extra,
        ),
        verdict_summary=verdict.summary,
    )

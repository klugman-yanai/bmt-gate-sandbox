"""Runtime and CLI entrypoint for the unified BMT framework."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import typer

from gcp.image.config.bmt_domain_status import BmtLegStatus, BmtProgressStatus, leg_status_is_pass
from gcp.image.config.constants import ENV_BMT_STATUS_CONTEXT, ENV_GCS_BUCKET, STATUS_CONTEXT
from gcp.image.runtime.artifacts import (
    aggregate_status,
    cleanup_ephemeral_triggers,
    latest_result_path,
    load_plan,
    load_summary,
    now_iso,
    plan_path,
    prune_snapshots,
    read_existing_last_passing,
    summary_path,
    verdict_result_path,
    write_current_pointer,
    write_plan,
    write_progress,
    write_summary,
)
from gcp.image.runtime.execution import execute_leg
from gcp.image.runtime.github_reporting import (
    ensure_reporting_metadata_for_plan,
    publish_final_results,
    publish_progress,
)
from gcp.image.runtime.importer import DatasetImporter, DatasetImportRequest
from gcp.image.runtime.models import (
    ExecutionPlan,
    LegSummary,
    PlanLeg,
    ProgressRecord,
    ScorePayload,
    StageRuntimePaths,
    WorkflowRequest,
)
from gcp.image.runtime.planning import PlanOptions, build_plan

app = typer.Typer(no_args_is_help=True)


def _default_runtime_root() -> Path:
    raw = (os.environ.get("BMT_RUNTIME_ROOT") or os.environ.get("BMT_STAGE_ROOT") or "").strip()
    if raw:
        return Path(raw).resolve()
    mounted_root = Path("/mnt/runtime")
    if mounted_root.exists():
        return mounted_root.resolve()
    return Path("gcp/stage").resolve()


def _default_workspace_root() -> Path:
    raw = (os.environ.get("BMT_FRAMEWORK_WORKSPACE") or "").strip()
    if raw:
        return Path(raw).resolve()
    return Path(tempfile.gettempdir(), "bmt-framework").resolve()


def _runtime_paths(stage_root: Path | None = None, workspace_root: Path | None = None) -> StageRuntimePaths:
    return StageRuntimePaths(
        stage_root=(stage_root or _default_runtime_root()).resolve(),
        workspace_root=(workspace_root or _default_workspace_root()).resolve(),
    )


def _bucket_uri(relative_path: str) -> str:
    bucket = (os.environ.get(ENV_GCS_BUCKET) or "").strip()
    if not bucket:
        return relative_path
    return f"gs://{bucket}/{relative_path.lstrip('/')}"


def _workflow_request_from_env(*, workflow_run_id: str) -> WorkflowRequest:
    accepted_projects_raw = (os.environ.get("BMT_ACCEPTED_PROJECTS_JSON") or "[]").strip()
    try:
        accepted_projects = json.loads(accepted_projects_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"BMT_ACCEPTED_PROJECTS_JSON must be valid JSON: {exc}") from exc
    if not isinstance(accepted_projects, list):
        raise TypeError("BMT_ACCEPTED_PROJECTS_JSON must decode to a JSON array")
    return WorkflowRequest(
        workflow_run_id=workflow_run_id,
        repository=(os.environ.get("GITHUB_REPOSITORY") or "").strip(),
        head_sha=(os.environ.get("BMT_HEAD_SHA") or "").strip(),
        head_branch=(os.environ.get("BMT_HEAD_BRANCH") or "").strip(),
        head_event=(os.environ.get("BMT_HEAD_EVENT") or "push").strip(),
        pr_number=(os.environ.get("BMT_PR_NUMBER") or "").strip(),
        run_context=(os.environ.get("BMT_RUN_CONTEXT") or "ci").strip(),
        accepted_projects=[str(project).strip() for project in accepted_projects if str(project).strip()],
        status_context=(os.environ.get(ENV_BMT_STATUS_CONTEXT) or STATUS_CONTEXT).strip(),
        use_mock_runner=(os.environ.get("BMT_USE_MOCK_RUNNER") or "").strip().lower() in {"1", "true", "yes"},
    )


def _build_plan(
    *, runtime: StageRuntimePaths, request: WorkflowRequest, allow_workspace_plugins: bool
) -> ExecutionPlan:
    return build_plan(
        runtime=runtime,
        options=PlanOptions(
            request=request,
            allow_workspace_plugins=allow_workspace_plugins,
        ),
    )


# Fields written to ci_verdict.json (subset of latest.json).
_VERDICT_FIELDS = frozenset(
    {
        "project",
        "bmt_slug",
        "bmt_id",
        "run_id",
        "status",
        "passed",
        "reason_code",
        "aggregate_score",
        "metrics",
        "extra",
    }
)


def _write_snapshot_artifacts(
    *,
    runtime: StageRuntimePaths,
    workflow_run_id: str,
    leg: PlanLeg,
    summary: LegSummary,
    logs_root: Path,
) -> LegSummary:
    latest_relative = latest_result_path(leg)
    verdict_relative = verdict_result_path(leg)
    logs_relative = f"{leg.results_path}/snapshots/{leg.run_id}/logs"
    latest_payload = {
        "project": summary.project,
        "bmt_slug": summary.bmt_slug,
        "bmt_id": summary.bmt_id,
        "run_id": summary.run_id,
        "status": summary.status,
        "passed": leg_status_is_pass(summary.status),
        "reason_code": summary.reason_code,
        "plugin_ref": summary.plugin_ref,
        "execution_mode_used": summary.execution_mode_used,
        "aggregate_score": summary.score.aggregate_score,
        "metrics": summary.score.metrics,
        "extra": summary.score.extra,
        "verdict_summary": summary.verdict_summary,
    }
    verdict_payload = {k: v for k, v in latest_payload.items() if k in _VERDICT_FIELDS}
    latest_path = runtime.stage_root / latest_relative
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(latest_payload, indent=2) + "\n", encoding="utf-8")
    verdict_path = runtime.stage_root / verdict_relative
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict_payload, indent=2) + "\n", encoding="utf-8")
    snapshot_logs_root = runtime.stage_root / logs_relative
    if logs_root.is_dir():
        shutil.copytree(logs_root, snapshot_logs_root, dirs_exist_ok=True)
    summary_relative = summary_path(workflow_run_id, summary.project, summary.bmt_slug)
    return summary.model_copy(
        update={
            "latest_uri": _bucket_uri(latest_relative),
            "ci_verdict_uri": _bucket_uri(verdict_relative),
            "summary_uri": _bucket_uri(summary_relative),
            "logs_uri": logs_relative,
        }
    )


def _task_leg(plan: ExecutionPlan, *, task_profile: str, task_index: int) -> PlanLeg:
    matching_legs = [leg for leg in plan.legs if leg.execution_profile == task_profile]
    if task_index < 0 or task_index >= len(matching_legs):
        raise IndexError(f"Task index {task_index} is outside the {task_profile} leg range ({len(matching_legs)})")
    return matching_legs[task_index]


def run_plan_mode(
    *, workflow_run_id: str, stage_root: Path | None = None, allow_workspace_plugins: bool = False
) -> int:
    if not workflow_run_id.strip():
        raise RuntimeError("BMT_WORKFLOW_RUN_ID is required for plan mode")
    runtime = _runtime_paths(stage_root=stage_root)
    request = _workflow_request_from_env(workflow_run_id=workflow_run_id)
    plan = _build_plan(runtime=runtime, request=request, allow_workspace_plugins=allow_workspace_plugins)
    write_plan(stage_root=runtime.stage_root, plan=plan)
    ensure_reporting_metadata_for_plan(plan=plan, runtime=runtime)
    typer.echo(plan.model_dump_json(indent=2))
    return 0


def run_task_mode(
    *,
    workflow_run_id: str,
    task_profile: str,
    task_index: int,
    stage_root: Path | None = None,
    workspace_root: Path | None = None,
) -> int:
    if not workflow_run_id.strip():
        raise RuntimeError("BMT_WORKFLOW_RUN_ID is required for task mode")
    runtime = _runtime_paths(stage_root=stage_root, workspace_root=workspace_root)
    plan = load_plan(stage_root=runtime.stage_root, workflow_run_id=workflow_run_id)
    leg = _task_leg(plan, task_profile=task_profile, task_index=task_index)
    run_root = runtime.workspace_root / leg.project / leg.bmt_slug / leg.run_id
    logs_root = run_root / "logs"
    started_at = now_iso()
    write_progress(
        stage_root=runtime.stage_root,
        workflow_run_id=workflow_run_id,
        progress=ProgressRecord(
            project=leg.project,
            bmt_slug=leg.bmt_slug,
            status=BmtProgressStatus.RUNNING.value,
            started_at=started_at,
            updated_at=started_at,
        ),
    )
    publish_progress(plan=plan, runtime=runtime)
    started_monotonic = time.monotonic()
    summary = execute_leg(plan=plan, leg=leg, runtime=runtime)
    duration_sec = max(0, int(time.monotonic() - started_monotonic))
    summary = summary.model_copy(update={"duration_sec": duration_sec})
    summary = _write_snapshot_artifacts(
        runtime=runtime,
        workflow_run_id=workflow_run_id,
        leg=leg,
        summary=summary,
        logs_root=logs_root,
    )
    write_summary(stage_root=runtime.stage_root, workflow_run_id=workflow_run_id, summary=summary)
    write_progress(
        stage_root=runtime.stage_root,
        workflow_run_id=workflow_run_id,
        progress=ProgressRecord(
            project=leg.project,
            bmt_slug=leg.bmt_slug,
            status=summary.status,
            started_at=started_at,
            updated_at=now_iso(),
            duration_sec=duration_sec,
            reason_code=summary.reason_code,
        ),
    )
    publish_progress(plan=plan, runtime=runtime)
    typer.echo(summary.model_dump_json(indent=2))
    return 0


def _load_summary_or_failure(*, stage_root: Path, workflow_run_id: str, leg: PlanLeg) -> LegSummary:
    try:
        return load_summary(
            stage_root=stage_root,
            workflow_run_id=workflow_run_id,
            project=leg.project,
            bmt_slug=leg.bmt_slug,
        )
    except FileNotFoundError:
        return LegSummary(
            project=leg.project,
            bmt_slug=leg.bmt_slug,
            bmt_id=leg.bmt_id,
            run_id=leg.run_id,
            status=BmtLegStatus.FAIL.value,
            reason_code="runner_failures",
            plugin_ref=leg.plugin_ref,
            execution_mode_used="unknown",
            score=ScorePayload(aggregate_score=0.0),
        )


def run_coordinator_mode(*, workflow_run_id: str, stage_root: Path | None = None) -> int:
    if not workflow_run_id.strip():
        raise RuntimeError("BMT_WORKFLOW_RUN_ID is required for coordinator mode")
    runtime = _runtime_paths(stage_root=stage_root)
    plan = load_plan(stage_root=runtime.stage_root, workflow_run_id=workflow_run_id)
    summaries = [
        _load_summary_or_failure(
            stage_root=runtime.stage_root,
            workflow_run_id=workflow_run_id,
            leg=leg,
        )
        for leg in plan.legs
    ]
    for leg, summary in zip(plan.legs, summaries, strict=True):
        results_root = runtime.stage_root / leg.results_path
        previous_last_passing = read_existing_last_passing(results_root)
        last_passing = summary.run_id if leg_status_is_pass(summary.status) else previous_last_passing
        write_current_pointer(results_root=results_root, run_id=summary.run_id, last_passing_run_id=last_passing)
        keep_run_ids = {summary.run_id}
        if last_passing:
            keep_run_ids.add(last_passing)
        prune_snapshots(results_root=results_root, keep_run_ids=keep_run_ids)
    publish_final_results(plan=plan, summaries=summaries, runtime=runtime)
    cleanup_ephemeral_triggers(stage_root=runtime.stage_root, plan=plan)
    typer.echo(json.dumps({"status": aggregate_status(summaries), "plan": plan_path(workflow_run_id)}, indent=2))
    return 0


def run_dataset_import_mode() -> int:
    request = DatasetImportRequest.from_env()
    if not request.is_ready():
        return 1
    return DatasetImporter().run(
        source_uri=request.source_uri,
        destination_prefix=request.destination_prefix,
    )


def run_local_mode(*, workflow_run_id: str, stage_root: Path | None = None, workspace_root: Path | None = None) -> int:
    runtime = _runtime_paths(stage_root=stage_root, workspace_root=workspace_root)
    plan = _build_plan(
        runtime=runtime,
        request=_workflow_request_from_env(workflow_run_id=workflow_run_id),
        allow_workspace_plugins=True,
    )
    write_plan(stage_root=runtime.stage_root, plan=plan)
    for task_profile in ("standard", "heavy"):
        task_count = getattr(plan, f"{task_profile}_task_count")
        for task_index in range(task_count):
            run_task_mode(
                workflow_run_id=workflow_run_id,
                task_profile=task_profile,
                task_index=task_index,
                stage_root=runtime.stage_root,
                workspace_root=runtime.workspace_root,
            )
    return run_coordinator_mode(workflow_run_id=workflow_run_id, stage_root=runtime.stage_root)


@app.command()
def plan(
    workflow_run_id: str,
    stage_root: Path | None = None,
    allow_workspace_plugins: bool = typer.Option(False, help="Allow mutable workspace plugin refs"),  # noqa: FBT001, FBT003
) -> None:
    raise typer.Exit(
        run_plan_mode(
            workflow_run_id=workflow_run_id,
            stage_root=stage_root,
            allow_workspace_plugins=allow_workspace_plugins,
        )
    )


@app.command()
def task(
    workflow_run_id: str,
    task_profile: str = "standard",
    task_index: int = 0,
    stage_root: Path | None = None,
    workspace_root: Path | None = None,
) -> None:
    raise typer.Exit(
        run_task_mode(
            workflow_run_id=workflow_run_id,
            task_profile=task_profile,
            task_index=task_index,
            stage_root=stage_root,
            workspace_root=workspace_root,
        )
    )


@app.command()
def coordinator(
    workflow_run_id: str,
    stage_root: Path | None = None,
) -> None:
    raise typer.Exit(run_coordinator_mode(workflow_run_id=workflow_run_id, stage_root=stage_root))


@app.command("run-local")
def run_local(
    workflow_run_id: str,
    stage_root: Path | None = None,
) -> None:
    raise typer.Exit(run_local_mode(workflow_run_id=workflow_run_id, stage_root=stage_root))


@app.command("dataset-import")
def dataset_import() -> None:
    raise typer.Exit(run_dataset_import_mode())


if __name__ == "__main__":
    app()

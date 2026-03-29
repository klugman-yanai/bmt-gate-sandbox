"""Runtime and CLI entrypoint for the unified BMT framework."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import override

import typer

from backend.config.bmt_domain_status import BmtLegStatus, BmtProgressStatus, leg_status_is_pass
from backend.config.constants import (
    ENV_BMT_FAILURE_REASON,
    ENV_BMT_FINALIZE_HEAD_SHA,
    ENV_BMT_FINALIZE_PR_NUMBER,
    ENV_BMT_FINALIZE_REPOSITORY,
    ENV_BMT_GCS_BUCKET_NAME,
    ENV_BMT_HANDOFF_RUN_URL,
    ENV_BMT_STATUS_CONTEXT,
    ENV_GCS_BUCKET,
    STATUS_CONTEXT,
)
from backend.config.decisions import ReasonCode
from backend.config.env_parse import is_truthy_env_value
from backend.runtime.artifacts import (
    aggregate_status,
    case_digest_result_path,
    cleanup_ephemeral_triggers,
    latest_result_path,
    load_optional_reporting_metadata,
    load_plan,
    load_summary_or_incomplete_plan_failure,
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
from backend.runtime.execution import execute_leg
from backend.runtime.finalization import (
    FinalizationState,
    LeaseAcquisitionError,
    acquire_results_path_leases,
    load_optional_finalization_record,
    release_results_path_leases,
    resolve_stage_bucket_name,
    update_finalization_record,
)
from backend.runtime.github_reporting import (
    ReportingPreflight,
    ensure_reporting_metadata_for_plan,
    publish_final_results,
    publish_github_failure,
    publish_progress,
    reporting_preflight,
)
from backend.runtime.hsm import HierarchicalStateMachine, State, UnsupportedTransitionError
from backend.runtime.importer import DatasetImporter, DatasetImportRequest
from backend.runtime.models import (
    ExecutionPlan,
    FinalizationRecord,
    LegSummary,
    PlanLeg,
    ProgressRecord,
    ScorePayload,
    StageRuntimePaths,
    WorkflowRequest,
)
from backend.runtime.planning import PlanOptions, build_plan

logger = logging.getLogger(__name__)

app = typer.Typer(no_args_is_help=True)


@dataclass(frozen=True, slots=True)
class SummaryCompleteness:
    expected_leg_count: int
    present_summary_count: int
    missing_leg_keys: list[str]
    extra_summary_keys: list[str]

    @property
    def has_gap(self) -> bool:
        return bool(self.missing_leg_keys or self.extra_summary_keys)

    @property
    def reconciliation_reason(self) -> str:
        reasons: list[str] = []
        if self.missing_leg_keys:
            reasons.append("missing_summaries")
        if self.extra_summary_keys:
            reasons.append("unexpected_summaries")
        return ",".join(reasons)


def _merge_reconciliation_reasons(*reasons: str) -> str:
    seen: list[str] = []
    for raw in reasons:
        for reason in raw.split(","):
            item = reason.strip()
            if item and item not in seen:
                seen.append(item)
    return ",".join(seen)


def _default_runtime_root() -> Path:
    raw = (os.environ.get("BMT_RUNTIME_ROOT") or os.environ.get("BMT_STAGE_ROOT") or "").strip()
    if raw:
        return Path(raw).resolve()
    mounted_root = Path("/mnt/runtime")
    if mounted_root.exists():
        return mounted_root.resolve()
    return Path("benchmarks").resolve()


def _default_workspace_root() -> Path:
    raw = (os.environ.get("BMT_FRAMEWORK_WORKSPACE") or "").strip()
    if raw:
        return Path(raw).resolve()
    return Path(tempfile.gettempdir(), "bmt-framework").resolve()


def _leg_summary_from_execute_failure(*, leg: PlanLeg, exc: BaseException) -> LegSummary:
    """When plugin execution raises, still produce a leg summary for the coordinator and GitHub."""
    msg = str(exc).strip() or repr(exc)
    return LegSummary(
        project=leg.project,
        bmt_slug=leg.bmt_slug,
        bmt_id=leg.bmt_id,
        run_id=leg.run_id,
        status=BmtLegStatus.FAIL.value,
        reason_code=ReasonCode.RUNNER_FAILURES.value,
        plugin_ref=leg.plugin_ref,
        execution_mode_used="unknown",
        score=ScorePayload(
            aggregate_score=0.0,
            metrics={
                "execute_exception_type": type(exc).__name__,
                "execute_exception_message": msg[:4000],
            },
            extra={"unavailable": True},
        ),
        verdict_summary={"execute_exception": type(exc).__name__, "message": msg[:8000]},
    )


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


def _case_digest_payload(summary: LegSummary) -> dict[str, object]:
    """Structured per-case outcomes for ``case_digest.json`` (mirrors ``metrics.case_outcomes`` when present)."""
    cases = summary.score.metrics.get("case_outcomes")
    if not isinstance(cases, list):
        cases = []
    return {
        "schema_version": 1,
        "project": summary.project,
        "bmt_slug": summary.bmt_slug,
        "run_id": summary.run_id,
        "execution_mode_used": summary.execution_mode_used,
        "reason_code": summary.reason_code,
        "cases": cases,
    }


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
        # Default off: real plugin/runner unless env explicitly opts in (CI sets this from workflows only when requested).
        use_mock_runner=is_truthy_env_value(os.environ.get("BMT_USE_MOCK_RUNNER")),
        handoff_run_url=(os.environ.get(ENV_BMT_HANDOFF_RUN_URL) or "").strip(),
        gcs_bucket=((os.environ.get(ENV_BMT_GCS_BUCKET_NAME) or os.environ.get(ENV_GCS_BUCKET) or "").strip()),
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
        "case_digest_uri",
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
    digest_relative = case_digest_result_path(leg)
    digest_path = runtime.stage_root / digest_relative
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(json.dumps(_case_digest_payload(summary), indent=2) + "\n", encoding="utf-8")
    case_digest_uri = _bucket_uri(digest_relative)

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
        "duration_sec": summary.duration_sec,
        "case_digest_uri": case_digest_uri,
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
            "case_digest_uri": case_digest_uri,
        }
    )


def _task_leg(plan: ExecutionPlan, *, task_profile: str, task_index: int) -> PlanLeg:
    matching_legs = [leg for leg in plan.legs if leg.execution_profile == task_profile]
    if task_index < 0 or task_index >= len(matching_legs):
        raise IndexError(f"Task index {task_index} is outside the {task_profile} leg range ({len(matching_legs)})")
    return matching_legs[task_index]


def _promote_current_pointers(
    *,
    runtime: StageRuntimePaths,
    plan: ExecutionPlan,
    summaries: list[LegSummary],
) -> list[str]:
    prune_targets: list[tuple[Path, set[str]]] = []
    promoted_results_paths: list[str] = []
    for leg, summary in zip(plan.legs, summaries, strict=True):
        results_root = runtime.stage_root / leg.results_path
        previous_last_passing = read_existing_last_passing(results_root)
        last_passing = summary.run_id if leg_status_is_pass(summary.status) else previous_last_passing
        write_current_pointer(
            results_root=results_root,
            run_id=summary.run_id,
            last_passing_run_id=last_passing,
            workflow_run_id=plan.workflow_run_id,
        )
        keep_run_ids = {summary.run_id}
        if last_passing:
            keep_run_ids.add(last_passing)
        prune_targets.append((results_root, keep_run_ids))
        promoted_results_paths.append(str(leg.results_path))
    for results_root, keep_run_ids in prune_targets:
        prune_snapshots(results_root=results_root, keep_run_ids=keep_run_ids)
    return promoted_results_paths


def _leg_key(*, project: str, bmt_slug: str) -> str:
    return f"{project}/{bmt_slug}"


def _log_coordinator_terminal_state(
    *,
    workflow_run_id: str,
    publish_required: bool,
    publish_done: bool,
    had_reporting_metadata: bool,
    had_check_run_id: bool,
    cleanup_kept_reporting_metadata: bool,
    finalization_state: FinalizationState | None,
) -> None:
    logger.info(
        "coordinator terminal state workflow_run_id=%s publish_required=%s publish_done=%s "
        "had_reporting_metadata=%s had_check_run_id=%s cleanup_kept_reporting_metadata=%s "
        "finalization_state=%s",
        workflow_run_id,
        publish_required,
        publish_done,
        had_reporting_metadata,
        had_check_run_id,
        cleanup_kept_reporting_metadata,
        finalization_state.value if finalization_state is not None else "",
    )


def _load_coordinator_summaries(
    *,
    runtime: StageRuntimePaths,
    plan: ExecutionPlan,
    workflow_run_id: str,
    log_completeness_warning: bool,
) -> tuple[list[LegSummary], SummaryCompleteness]:
    summaries_root = runtime.stage_root / "triggers" / "summaries" / workflow_run_id
    present_summary_paths = (
        {
            str(path.relative_to(runtime.stage_root))
            for path in sorted(summaries_root.glob("*.json"))
            if path.is_file()
        }
        if summaries_root.is_dir()
        else set()
    )
    expected_summary_paths = {
        summary_path(workflow_run_id, leg.project, leg.bmt_slug): leg
        for leg in plan.legs
    }
    missing_leg_keys = [
        _leg_key(project=leg.project, bmt_slug=leg.bmt_slug)
        for leg in plan.legs
        if summary_path(workflow_run_id, leg.project, leg.bmt_slug) not in present_summary_paths
    ]
    extra_summary_keys = sorted(path for path in present_summary_paths if path not in expected_summary_paths)
    completeness = SummaryCompleteness(
        expected_leg_count=len(plan.legs),
        present_summary_count=len(present_summary_paths),
        missing_leg_keys=missing_leg_keys,
        extra_summary_keys=extra_summary_keys,
    )
    if log_completeness_warning and completeness.has_gap:
        logger.warning(
            "event=coordinator_completeness_incomplete workflow_run_id=%s expected_leg_count=%s "
            "present_summary_count=%s missing_leg_keys=%s extra_summary_keys=%s",
            workflow_run_id,
            completeness.expected_leg_count,
            completeness.present_summary_count,
            completeness.missing_leg_keys,
            completeness.extra_summary_keys,
        )
    return (
        [
            load_summary_or_incomplete_plan_failure(
                stage_root=runtime.stage_root,
                workflow_run_id=workflow_run_id,
                leg=leg,
            )
            for leg in plan.legs
        ],
        completeness,
    )


def _run_coordinator_publish_stage(
    *,
    plan: ExecutionPlan,
    runtime: StageRuntimePaths,
    summaries: list[LegSummary],
    existing_finalization: FinalizationRecord | None,
    preflight: ReportingPreflight,
) -> tuple[bool, str]:
    if existing_finalization is not None and existing_finalization.github_publish_complete:
        return True, ""
    if not preflight.publish_required:
        return False, ""
    try:
        publish_final_results(plan=plan, summaries=summaries, runtime=runtime)
        meta = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
        publish_done = meta is not None and meta.github_publish_complete
        if not publish_done:
            publish_github_failure(
                plan=plan,
                runtime=runtime,
                reason="Coordinator could not complete GitHub terminal publish after pointer promotion.",
            )
            meta = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
            publish_done = meta is not None and meta.github_publish_complete
    except Exception as exc:
        logger.exception("coordinator publish stage failed workflow_run_id=%s", plan.workflow_run_id)
        return False, str(exc)
    return publish_done, "" if publish_done else "GitHub terminal publish did not complete."


class CoordinatorPhase(Enum):
    """Coordinator finalization phases (distinct from persisted :class:`FinalizationState`)."""

    PREPARED = auto()
    AWAITING_GITHUB_PUBLISH = auto()
    SUCCESS = auto()
    FAILED_GITHUB = auto()
    FAILED_PROMOTION = auto()


class CoordinatorFinalizeEvent(Enum):
    REPORTER_UNREADY = auto()
    PROMOTION_OK = auto()
    PUBLISH_OK = auto()
    PUBLISH_FAILED = auto()


class _CoordinatorFsmState(State):
    __slots__ = ("_machine",)

    def __init__(self, machine: CoordinatorFinalizationMachine) -> None:
        self._machine = machine


class _ActiveCoordinatorState(_CoordinatorFsmState):
    """In-progress phases that may still fail."""

    def on_reporter_unready(self) -> None:
        raise UnsupportedTransitionError(f"{type(self).__name__!r} does not handle reporter_unready")

    def on_promotion_ok(self) -> None:
        raise UnsupportedTransitionError(f"{type(self).__name__!r} does not handle promotion_ok")

    def on_publish_ok(self) -> None:
        raise UnsupportedTransitionError(f"{type(self).__name__!r} does not handle publish_ok")

    def on_publish_failed(self) -> None:
        raise UnsupportedTransitionError(f"{type(self).__name__!r} does not handle publish_failed")


class _PreparedCoordinatorState(_ActiveCoordinatorState):
    @override
    def on_enter(self) -> None:
        m = self._machine
        record = update_finalization_record(
            stage_root=m.runtime.stage_root,
            workflow_run_id=m.plan.workflow_run_id,
            repository=m.plan.repository,
            head_sha=m.plan.head_sha,
            state=FinalizationState.PREPARED,
            publish_required=m.publish_required,
            github_publish_complete=False,
            promoted_results_paths=[],
            lease_keys=m.lease_keys,
            expected_leg_count=m.completeness.expected_leg_count,
            present_summary_count=m.completeness.present_summary_count,
            missing_leg_keys=m.completeness.missing_leg_keys,
            extra_summary_keys=m.completeness.extra_summary_keys,
            needs_reconciliation=m.completeness.has_gap,
            reconciliation_reason=m.completeness.reconciliation_reason,
        )
        m.prepared_at = record.prepared_at

    @override
    def on_reporter_unready(self) -> None:
        m = self._machine
        m.failure_error_message = (
            "GitHub terminal publish is required but the reporter is not ready."
        )
        m.transition(CoordinatorPhase.FAILED_GITHUB)

    @override
    def on_promotion_ok(self) -> None:
        self._machine.transition(CoordinatorPhase.AWAITING_GITHUB_PUBLISH)


class _AwaitingGithubPublishState(_ActiveCoordinatorState):
    @override
    def on_enter(self) -> None:
        m = self._machine
        update_finalization_record(
            stage_root=m.runtime.stage_root,
            workflow_run_id=m.plan.workflow_run_id,
            repository=m.plan.repository,
            head_sha=m.plan.head_sha,
            state=FinalizationState.PROMOTION_COMMITTED,
            publish_required=m.publish_required,
            github_publish_complete=m.publish_done,
            promoted_results_paths=m.promoted_results_paths,
            lease_keys=m.lease_keys,
            expected_leg_count=m.completeness.expected_leg_count,
            present_summary_count=m.completeness.present_summary_count,
            missing_leg_keys=m.completeness.missing_leg_keys,
            extra_summary_keys=m.completeness.extra_summary_keys,
            needs_reconciliation=m.completeness.has_gap,
            reconciliation_reason=m.completeness.reconciliation_reason,
            prepared_at=m.prepared_at,
        )

    @override
    def on_publish_ok(self) -> None:
        self._machine.transition(CoordinatorPhase.SUCCESS)

    @override
    def on_publish_failed(self) -> None:
        self._machine.transition(CoordinatorPhase.FAILED_GITHUB)


class _CoordinatorSuccessState(_CoordinatorFsmState):
    @override
    def on_enter(self) -> None:
        m = self._machine
        update_finalization_record(
            stage_root=m.runtime.stage_root,
            workflow_run_id=m.plan.workflow_run_id,
            repository=m.plan.repository,
            head_sha=m.plan.head_sha,
            state=FinalizationState.PROMOTION_COMMITTED,
            publish_required=m.publish_required,
            github_publish_complete=m.publish_done,
            promoted_results_paths=m.promoted_results_paths,
            lease_keys=m.lease_keys,
            expected_leg_count=m.completeness.expected_leg_count,
            present_summary_count=m.completeness.present_summary_count,
            missing_leg_keys=m.completeness.missing_leg_keys,
            extra_summary_keys=m.completeness.extra_summary_keys,
            needs_reconciliation=m.completeness.has_gap,
            reconciliation_reason=m.completeness.reconciliation_reason,
            prepared_at=m.prepared_at,
        )
        cleanup_ephemeral_triggers(stage_root=m.runtime.stage_root, plan=m.plan, keep_reporting_metadata=False)


class _FailedGithubPublishState(_CoordinatorFsmState):
    @override
    def on_enter(self) -> None:
        m = self._machine
        update_finalization_record(
            stage_root=m.runtime.stage_root,
            workflow_run_id=m.plan.workflow_run_id,
            repository=m.plan.repository,
            head_sha=m.plan.head_sha,
            state=FinalizationState.FAILED_GITHUB_PUBLISH,
            publish_required=m.publish_required,
            github_publish_complete=False,
            promoted_results_paths=m.promoted_results_paths,
            lease_keys=m.lease_keys,
            expected_leg_count=m.completeness.expected_leg_count,
            present_summary_count=m.completeness.present_summary_count,
            missing_leg_keys=m.completeness.missing_leg_keys,
            extra_summary_keys=m.completeness.extra_summary_keys,
            needs_reconciliation=True,
            reconciliation_reason=_merge_reconciliation_reasons(
                m.completeness.reconciliation_reason,
                "github_publish_failed",
            ),
            error_message=m.failure_error_message,
            prepared_at=m.prepared_at,
        )


class _FailedPromotionState(_CoordinatorFsmState):
    @override
    def on_enter(self) -> None:
        m = self._machine
        update_finalization_record(
            stage_root=m.runtime.stage_root,
            workflow_run_id=m.plan.workflow_run_id,
            repository=m.plan.repository,
            head_sha=m.plan.head_sha,
            state=FinalizationState.FAILED_PROMOTION,
            publish_required=m.publish_required,
            github_publish_complete=m.publish_done,
            promoted_results_paths=m.promoted_results_paths,
            lease_keys=m.lease_keys,
            expected_leg_count=m.completeness.expected_leg_count,
            present_summary_count=m.completeness.present_summary_count,
            missing_leg_keys=m.completeness.missing_leg_keys,
            extra_summary_keys=m.completeness.extra_summary_keys,
            needs_reconciliation=True,
            reconciliation_reason=_merge_reconciliation_reasons(
                m.completeness.reconciliation_reason,
                "promotion_failed",
            ),
            error_message=m.failure_error_message,
            prepared_at=m.prepared_at,
        )


class CoordinatorFinalizationMachine(HierarchicalStateMachine[CoordinatorPhase, CoordinatorFinalizeEvent]):
    """Hierarchical state machine for coordinator pointer promotion and GitHub publish."""

    def __init__(
        self,
        *,
        runtime: StageRuntimePaths,
        plan: ExecutionPlan,
        summaries: list[LegSummary],
        completeness: SummaryCompleteness,
        lease_keys: list[str],
        publish_required: bool,
        preflight: ReportingPreflight,
        existing_finalization: FinalizationRecord | None,
    ) -> None:
        self.runtime = runtime
        self.plan = plan
        self.summaries = summaries
        self.completeness = completeness
        self.lease_keys = lease_keys
        self.publish_required = publish_required
        self.preflight = preflight
        self.existing_finalization = existing_finalization
        self.promoted_results_paths: list[str] = []
        self.publish_done = False
        self.publish_error = ""
        self.prepared_at = ""
        self.failure_error_message = ""
        super().__init__(CoordinatorPhase.PREPARED)

    @override
    def _build_states(self) -> dict[CoordinatorPhase, State]:
        return {
            CoordinatorPhase.PREPARED: _PreparedCoordinatorState(self),
            CoordinatorPhase.AWAITING_GITHUB_PUBLISH: _AwaitingGithubPublishState(self),
            CoordinatorPhase.SUCCESS: _CoordinatorSuccessState(self),
            CoordinatorPhase.FAILED_GITHUB: _FailedGithubPublishState(self),
            CoordinatorPhase.FAILED_PROMOTION: _FailedPromotionState(self),
        }


def _drive_coordinator_finalization(
    *,
    machine: CoordinatorFinalizationMachine,
    workflow_run_id: str,
    publish_required: bool,
    preflight: ReportingPreflight,
    had_reporting_metadata: bool,
    had_check_run_id: bool,
) -> int:
    """Run promotion + publish; drive the finalization machine. Returns exit code."""
    if publish_required and not preflight.reporter_ready:
        machine.on_message(CoordinatorFinalizeEvent.REPORTER_UNREADY)
        logger.error(
            "coordinator publish preflight failed workflow_run_id=%s publish_required=%s reporter_ready=%s",
            workflow_run_id,
            publish_required,
            preflight.reporter_ready,
        )
        _log_coordinator_terminal_state(
            workflow_run_id=workflow_run_id,
            publish_required=publish_required,
            publish_done=False,
            had_reporting_metadata=had_reporting_metadata,
            had_check_run_id=had_check_run_id,
            cleanup_kept_reporting_metadata=True,
            finalization_state=FinalizationState.FAILED_GITHUB_PUBLISH,
        )
        return 1
    try:
        machine.promoted_results_paths = _promote_current_pointers(
            runtime=machine.runtime,
            plan=machine.plan,
            summaries=machine.summaries,
        )
    except Exception as exc:
        machine.failure_error_message = str(exc)
        machine.publish_done = False
        machine.transition(CoordinatorPhase.FAILED_PROMOTION)
        logger.exception("coordinator promotion stage failed workflow_run_id=%s", workflow_run_id)
        _log_coordinator_terminal_state(
            workflow_run_id=workflow_run_id,
            publish_required=publish_required,
            publish_done=False,
            had_reporting_metadata=had_reporting_metadata,
            had_check_run_id=had_check_run_id,
            cleanup_kept_reporting_metadata=publish_required,
            finalization_state=FinalizationState.FAILED_PROMOTION,
        )
        return 1

    machine.on_message(CoordinatorFinalizeEvent.PROMOTION_OK)
    machine.publish_done, machine.publish_error = _run_coordinator_publish_stage(
        plan=machine.plan,
        runtime=machine.runtime,
        summaries=machine.summaries,
        existing_finalization=machine.existing_finalization,
        preflight=machine.preflight,
    )
    if publish_required and not machine.publish_done:
        machine.failure_error_message = machine.publish_error
        machine.on_message(CoordinatorFinalizeEvent.PUBLISH_FAILED)
        _log_coordinator_terminal_state(
            workflow_run_id=workflow_run_id,
            publish_required=publish_required,
            publish_done=machine.publish_done,
            had_reporting_metadata=had_reporting_metadata,
            had_check_run_id=had_check_run_id,
            cleanup_kept_reporting_metadata=publish_required and not machine.publish_done,
            finalization_state=FinalizationState.FAILED_GITHUB_PUBLISH,
        )
        return 1

    machine.on_message(CoordinatorFinalizeEvent.PUBLISH_OK)
    _log_coordinator_terminal_state(
        workflow_run_id=workflow_run_id,
        publish_required=publish_required,
        publish_done=machine.publish_done,
        had_reporting_metadata=had_reporting_metadata,
        had_check_run_id=had_check_run_id,
        cleanup_kept_reporting_metadata=False,
        finalization_state=FinalizationState.PROMOTION_COMMITTED,
    )
    typer.echo(
        json.dumps({"status": aggregate_status(machine.summaries), "plan": plan_path(workflow_run_id)}, indent=2)
    )
    return 0


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
    try:
        summary = execute_leg(plan=plan, leg=leg, runtime=runtime)
    except Exception as exc:
        logger.exception(
            "execute_leg failed workflow_run_id=%s project=%s bmt=%s",
            workflow_run_id,
            leg.project,
            leg.bmt_slug,
        )
        summary = _leg_summary_from_execute_failure(leg=leg, exc=exc)
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


def run_coordinator_mode(*, workflow_run_id: str, stage_root: Path | None = None) -> int:
    if not workflow_run_id.strip():
        raise RuntimeError("BMT_WORKFLOW_RUN_ID is required for coordinator mode")
    runtime = _runtime_paths(stage_root=stage_root)
    plan = load_plan(stage_root=runtime.stage_root, workflow_run_id=workflow_run_id)
    preflight = reporting_preflight(plan=plan, runtime=runtime)
    publish_required = preflight.publish_required
    had_reporting_metadata = preflight.metadata.has_check_run_and_details_url()
    had_check_run_id = preflight.metadata.check_run_id is not None
    existing_finalization = load_optional_finalization_record(stage_root=runtime.stage_root, workflow_run_id=workflow_run_id)
    if (
        existing_finalization is not None
        and existing_finalization.state == FinalizationState.PROMOTION_COMMITTED
        and (not existing_finalization.publish_required or existing_finalization.github_publish_complete)
    ):
        cleanup_ephemeral_triggers(stage_root=runtime.stage_root, plan=plan, keep_reporting_metadata=False)
        _log_coordinator_terminal_state(
            workflow_run_id=workflow_run_id,
            publish_required=existing_finalization.publish_required,
            publish_done=existing_finalization.github_publish_complete,
            had_reporting_metadata=had_reporting_metadata,
            had_check_run_id=had_check_run_id,
            cleanup_kept_reporting_metadata=False,
            finalization_state=FinalizationState.PROMOTION_COMMITTED,
        )
        return 0

    summaries, completeness = _load_coordinator_summaries(
        runtime=runtime,
        plan=plan,
        workflow_run_id=workflow_run_id,
        log_completeness_warning=True,
    )
    lease_handles = []
    lease_keys: list[str] = []
    try:
        lease_handles = acquire_results_path_leases(
            stage_root=runtime.stage_root,
            workflow_run_id=workflow_run_id,
            results_paths=[str(leg.results_path) for leg in plan.legs],
            bucket_name=resolve_stage_bucket_name(plan_bucket_name=plan.gcs_bucket),
        )
        lease_keys = [handle.lease_key for handle in lease_handles]
    except LeaseAcquisitionError as exc:
        update_finalization_record(
            stage_root=runtime.stage_root,
            workflow_run_id=workflow_run_id,
            repository=plan.repository,
            head_sha=plan.head_sha,
            state=FinalizationState.FAILED_PROMOTION,
            publish_required=publish_required,
            github_publish_complete=False,
            promoted_results_paths=[],
            lease_keys=[],
            expected_leg_count=completeness.expected_leg_count,
            present_summary_count=completeness.present_summary_count,
            missing_leg_keys=completeness.missing_leg_keys,
            extra_summary_keys=completeness.extra_summary_keys,
            needs_reconciliation=True,
            reconciliation_reason=_merge_reconciliation_reasons(
                completeness.reconciliation_reason,
                "lease_acquisition_failed",
            ),
            error_message=str(exc),
        )
        logger.exception("coordinator lease acquisition failed workflow_run_id=%s", workflow_run_id)
        _log_coordinator_terminal_state(
            workflow_run_id=workflow_run_id,
            publish_required=publish_required,
            publish_done=False,
            had_reporting_metadata=had_reporting_metadata,
            had_check_run_id=had_check_run_id,
            cleanup_kept_reporting_metadata=publish_required,
            finalization_state=FinalizationState.FAILED_PROMOTION,
        )
        return 1

    try:
        machine = CoordinatorFinalizationMachine(
            runtime=runtime,
            plan=plan,
            summaries=summaries,
            completeness=completeness,
            lease_keys=lease_keys,
            publish_required=publish_required,
            preflight=preflight,
            existing_finalization=existing_finalization,
        )
        return _drive_coordinator_finalization(
            machine=machine,
            workflow_run_id=workflow_run_id,
            publish_required=publish_required,
            preflight=preflight,
            had_reporting_metadata=had_reporting_metadata,
            had_check_run_id=had_check_run_id,
        )
    finally:
        release_results_path_leases(handles=lease_handles)


def run_finalize_failure_mode(*, workflow_run_id: str, stage_root: Path | None = None) -> int:
    """Workflow failure hook: close dangling GitHub check using summaries on disk when possible."""
    if not workflow_run_id.strip():
        raise RuntimeError("BMT_WORKFLOW_RUN_ID is required for finalize-failure mode")
    runtime = _runtime_paths(stage_root=stage_root)
    reason = (os.environ.get(ENV_BMT_FAILURE_REASON) or "").strip() or (
        "BMT Google Workflow aborted before coordinator completed."
    )
    plan: ExecutionPlan | None = None
    try:
        plan = load_plan(stage_root=runtime.stage_root, workflow_run_id=workflow_run_id)
    except FileNotFoundError:
        repo = (os.environ.get(ENV_BMT_FINALIZE_REPOSITORY) or "").strip()
        sha = (os.environ.get(ENV_BMT_FINALIZE_HEAD_SHA) or "").strip()
        prn = (os.environ.get(ENV_BMT_FINALIZE_PR_NUMBER) or "").strip()
        status_ctx = (os.environ.get(ENV_BMT_STATUS_CONTEXT) or STATUS_CONTEXT).strip()
        if repo and sha:
            logger.info(
                "finalize-failure: no plan file; using %s / %s for GitHub close workflow_run_id=%s",
                ENV_BMT_FINALIZE_REPOSITORY,
                ENV_BMT_FINALIZE_HEAD_SHA,
                workflow_run_id,
            )
            plan = ExecutionPlan(
                workflow_run_id=workflow_run_id,
                repository=repo,
                head_sha=sha,
                head_branch="",
                head_event="pull_request",
                pr_number=prn,
                run_context="pr",
                status_context=status_ctx,
                handoff_run_url=(os.environ.get(ENV_BMT_HANDOFF_RUN_URL) or "").strip(),
                gcs_bucket=(os.environ.get(ENV_BMT_GCS_BUCKET_NAME) or "").strip(),
                legs=[],
                standard_task_count=0,
                heavy_task_count=0,
                accepted_projects=[],
            )
        else:
            logger.info(
                "finalize-failure: no plan on disk and no %s/%s; cannot close GitHub check workflow_run_id=%s",
                ENV_BMT_FINALIZE_REPOSITORY,
                ENV_BMT_FINALIZE_HEAD_SHA,
                workflow_run_id,
            )
            return 0
    publish_github_failure(plan=plan, runtime=runtime, reason=reason[:500])
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


@app.command("finalize-failure")
def finalize_failure(
    workflow_run_id: str,
    stage_root: Path | None = None,
) -> None:
    raise typer.Exit(
        run_finalize_failure_mode(workflow_run_id=workflow_run_id, stage_root=stage_root),
    )


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

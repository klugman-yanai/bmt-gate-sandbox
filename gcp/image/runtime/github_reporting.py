from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

import google.auth
import httpx
import whenever
from google.api_core import exceptions as google_api_exceptions
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request
from google.cloud import storage as gcs_storage

from gcp.image.config.bmt_domain_status import BmtLegStatus, BmtProgressStatus, leg_status_is_pass
from gcp.image.config.constants import ENV_BMT_WORKFLOW_EXECUTION_URL, ENV_GCS_BUCKET
from gcp.image.config.status import CheckConclusion, CommitStatus
from gcp.image.github.github_auth import resolve_github_app_token
from gcp.image.github.presentation import (
    CheckFinalView,
    CheckProgressView,
    FinalBmtRow,
    FinalCommentView,
    LiveLinks,
    ProgressBmtRow,
    StartedCommentView,
    human_reason,
)
from gcp.image.github.reporting import GitHubReporter
from gcp.image.runtime.artifacts import (
    aggregate_status,
    load_optional_progress,
    load_optional_reporting_metadata,
    now_iso,
    summary_path,
    write_reporting_metadata,
)
from gcp.image.runtime.models import ExecutionPlan, LegSummary, ReportingMetadata, StageRuntimePaths

logger = logging.getLogger(__name__)


def _reporting_metadata_fully_initialized(existing: ReportingMetadata | None) -> bool:
    return bool(
        existing and existing.check_run_id is not None and (existing.workflow_execution_url or "").strip()
    )


def _merge_missing_workflow_url_only(
    *,
    existing: ReportingMetadata | None,
    plan: ExecutionPlan,
    runtime: StageRuntimePaths,
    workflow_url: str,
) -> bool:
    """If metadata has a check run but no URL and env provides one, persist URL and return True."""
    if not (
        existing
        and existing.check_run_id is not None
        and workflow_url
        and not (existing.workflow_execution_url or "").strip()
    ):
        return False
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=existing.model_copy(update={"workflow_execution_url": workflow_url}),
    )
    return True


def _persist_reporting_started(
    *,
    runtime: StageRuntimePaths,
    plan: ExecutionPlan,
    workflow_url: str,
    check_run_id: int,
) -> None:
    write_reporting_metadata(
        stage_root=runtime.stage_root,
        workflow_run_id=plan.workflow_run_id,
        metadata=ReportingMetadata(
            workflow_execution_url=workflow_url,
            check_run_id=check_run_id,
            started_at=now_iso(),
        ),
    )


def ensure_reporting_metadata_for_plan(*, plan: ExecutionPlan, runtime: StageRuntimePaths) -> None:
    """Create GitHub Check Run (in progress) and write triggers/reporting/{workflow_run_id}.json.

    Idempotent: skips if metadata already has check_run_id and workflow_execution_url. Does not fail
    the plan when GitHub or env is unavailable (logs a warning).
    """
    existing = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
    workflow_url = (os.environ.get(ENV_BMT_WORKFLOW_EXECUTION_URL) or "").strip()

    if _reporting_metadata_fully_initialized(existing):
        return
    if _merge_missing_workflow_url_only(
        existing=existing, plan=plan, runtime=runtime, workflow_url=workflow_url
    ):
        return

    workflow_url, token = _reporting_preconditions(plan=plan, workflow_url=workflow_url)
    if workflow_url is None or token is None:
        return

    reporter = GitHubReporter(
        repository=plan.repository,
        sha=plan.head_sha,
        token=token,
        status_context=plan.status_context,
    )
    view = StartedCommentView(head_sha=plan.head_sha, links=LiveLinks(workflow_execution_url=workflow_url))
    try:
        check_run_id = reporter.create_started_check_run(
            view,
            details_url=workflow_url,
            external_id=plan.workflow_run_id,
            pending_legs=[(leg.project, leg.bmt_slug) for leg in plan.legs],
        )
    except httpx.HTTPError:
        logger.exception("create_started_check_run failed workflow_run_id=%s", plan.workflow_run_id)
        return
    if plan.pr_number.isdigit():
        try:
            reporter.upsert_started_pr_comment(pr_number=int(plan.pr_number), view=view)
        except httpx.HTTPError:
            logger.warning("upsert_started_pr_comment failed workflow_run_id=%s", plan.workflow_run_id, exc_info=True)
    _persist_reporting_started(
        runtime=runtime, plan=plan, workflow_url=workflow_url, check_run_id=check_run_id
    )


def _reporting_preconditions(*, plan: ExecutionPlan, workflow_url: str) -> tuple[str, str] | tuple[None, None]:
    """Validate preconditions for creating a check run.

    Returns (workflow_url, token) if all preconditions are met, or (None, None) with a logged
    warning for each missing requirement.
    """
    if not workflow_url:
        logger.warning("missing %s workflow_run_id=%s", ENV_BMT_WORKFLOW_EXECUTION_URL, plan.workflow_run_id)
        return None, None
    if not plan.repository or not plan.head_sha:
        logger.warning("missing repository or head_sha workflow_run_id=%s", plan.workflow_run_id)
        return None, None
    token = resolve_github_app_token(plan.repository)
    if not token:
        logger.warning("no GitHub token workflow_run_id=%s", plan.workflow_run_id)
        return None, None
    return workflow_url, token


def publish_progress(*, plan: ExecutionPlan, runtime: StageRuntimePaths) -> None:
    reporter, metadata = _load_reporter(plan=plan, runtime=runtime)
    if reporter is None:
        return
    if metadata.check_run_id is None or not metadata.workflow_execution_url:
        logger.debug(
            "publish_progress skipped: missing check_run_id or workflow_execution_url workflow_run_id=%s",
            plan.workflow_run_id,
        )
        return
    try:
        reporter.update_progress_check_run(
            check_run_id=metadata.check_run_id,
            view=_progress_view(plan=plan, runtime=runtime, workflow_execution_url=metadata.workflow_execution_url),
            details_url=metadata.workflow_execution_url,
        )
    except httpx.HTTPError:
        logger.warning("publish_progress failed workflow_run_id=%s", plan.workflow_run_id, exc_info=True)


def _aggregate_pass_and_commit_states(
    summaries: list[LegSummary],
) -> tuple[bool, str, str]:
    is_pass = aggregate_status(summaries) == BmtLegStatus.PASS.value
    check_state = CheckConclusion.SUCCESS.value if is_pass else CheckConclusion.FAILURE.value
    commit_state = CommitStatus.SUCCESS.value if is_pass else CommitStatus.FAILURE.value
    return is_pass, check_state, commit_state


def _commit_status_description(summaries: list[LegSummary], *, is_pass: bool) -> str:
    if not summaries:
        return "No BMT legs completed."
    n_failed = sum(1 for s in summaries if not leg_status_is_pass(s.status))
    if is_pass:
        return f"{len(summaries)} BMTs passed."
    return f"{n_failed}/{len(summaries)} BMTs failed."


def publish_final_results(*, plan: ExecutionPlan, summaries: list[LegSummary], runtime: StageRuntimePaths) -> None:
    reporter, metadata = _load_reporter(plan=plan, runtime=runtime)
    if reporter is None:
        return

    workflow_url = metadata.workflow_execution_url
    log_dump_url = _write_log_dump_and_sign(plan=plan, runtime=runtime, summaries=summaries)
    final_view = _final_view(
        summaries=summaries,
        workflow_execution_url=workflow_url,
        log_dump_url=log_dump_url,
    )
    is_pass, check_state, commit_state = _aggregate_pass_and_commit_states(summaries)
    description = _commit_status_description(summaries, is_pass=is_pass)

    try:
        _, finalized_ok = reporter.finalize_check_run(
            check_run_id=metadata.check_run_id,
            view=final_view,
            details_url=workflow_url,
        )
    except httpx.HTTPError:
        logger.warning("finalize_check_run failed workflow_run_id=%s", plan.workflow_run_id, exc_info=True)
    else:
        if not finalized_ok:
            logger.warning(
                "finalize_check_run did not complete successfully workflow_run_id=%s",
                plan.workflow_run_id,
            )

    try:
        reporter.post_final_status(
            state=commit_state,
            description=description,
            details_url=workflow_url or None,
        )
    except httpx.HTTPError:
        logger.warning("post_final_status failed workflow_run_id=%s", plan.workflow_run_id, exc_info=True)

    if not plan.pr_number.isdigit():
        return
    try:
        reporter.upsert_final_pr_comment(
            pr_number=int(plan.pr_number),
            view=FinalCommentView(
                head_sha=plan.head_sha,
                state=check_state,
                links=LiveLinks(workflow_execution_url=workflow_url, log_dump_url=log_dump_url),
                failed_bmts=_final_comment_failed_rows(summaries),
            ),
        )
    except httpx.HTTPError:
        logger.warning("upsert_final_pr_comment failed workflow_run_id=%s", plan.workflow_run_id, exc_info=True)


def _load_reporter(
    *, plan: ExecutionPlan, runtime: StageRuntimePaths
) -> tuple[GitHubReporter | None, ReportingMetadata]:
    if not plan.repository or not plan.head_sha:
        return None, ReportingMetadata()
    token = resolve_github_app_token(plan.repository)
    if not token:
        metadata = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
        return None, metadata or ReportingMetadata()
    metadata = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=plan.workflow_run_id)
    return (
        GitHubReporter(
            repository=plan.repository,
            sha=plan.head_sha,
            token=token,
            status_context=plan.status_context,
        ),
        metadata or ReportingMetadata(),
    )


def _progress_view(
    *, plan: ExecutionPlan, runtime: StageRuntimePaths, workflow_execution_url: str
) -> CheckProgressView:
    rows: list[ProgressBmtRow] = []
    completed_count = 0
    for leg in plan.legs:
        summary_file = runtime.stage_root / summary_path(plan.workflow_run_id, leg.project, leg.bmt_slug)
        if summary_file.is_file():
            summary = LegSummary.model_validate_json(summary_file.read_text(encoding="utf-8"))
            rows.append(
                ProgressBmtRow(
                    project=summary.project,
                    bmt=summary.bmt_slug,
                    status=summary.status,
                    duration_sec=summary.duration_sec,
                    aggregate_score=summary.score.aggregate_score,
                    execution_mode_used=summary.execution_mode_used,
                    cases_detail=_cases_detail_from_metrics(summary.score.metrics),
                )
            )
            completed_count += 1
            continue
        progress = load_optional_progress(
            stage_root=runtime.stage_root,
            workflow_run_id=plan.workflow_run_id,
            project=leg.project,
            bmt_slug=leg.bmt_slug,
        )
        rows.append(
            ProgressBmtRow(
                project=leg.project,
                bmt=leg.bmt_slug,
                status=progress.status if progress else BmtProgressStatus.PENDING.value,
                duration_sec=progress.duration_sec if progress else None,
            )
        )
    return CheckProgressView(
        completed_count=completed_count,
        total_count=len(plan.legs),
        elapsed_sec=_elapsed_seconds(runtime=runtime, workflow_run_id=plan.workflow_run_id),
        eta_sec=None,
        links=LiveLinks(workflow_execution_url=workflow_execution_url),
        bmts=rows,
    )


def _cases_detail_from_metrics(metrics: dict[str, object]) -> str:
    cases_ok = metrics.get("cases_ok")
    case_count = metrics.get("case_count")
    if cases_ok is None or case_count is None:
        return ""
    return f"{cases_ok}/{case_count} ok"


def _final_comment_failed_rows(summaries: list[LegSummary]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for summary in summaries:
        if leg_status_is_pass(summary.status):
            continue
        detail = human_reason(summary.reason_code)
        if summary.reason_code == "runner_case_failures":
            detail += (
                f" ({summary.score.metrics.get('cases_failed', '?')} of"
                f" {summary.score.metrics.get('case_count', '?')} cases crashed)"
            )
        rows.append((summary.bmt_slug, detail))
    return rows


def _final_view(
    *, summaries: list[LegSummary], workflow_execution_url: str, log_dump_url: str | None
) -> CheckFinalView:
    is_pass = aggregate_status(summaries) == BmtLegStatus.PASS.value
    check_state = CheckConclusion.SUCCESS.value if is_pass else CheckConclusion.FAILURE.value
    return CheckFinalView(
        state=check_state,
        links=LiveLinks(workflow_execution_url=workflow_execution_url, log_dump_url=log_dump_url),
        bmts=[
            FinalBmtRow(
                project=summary.project,
                bmt=summary.bmt_slug,
                status=summary.status,
                aggregate_score=summary.score.aggregate_score,
                reason_code=summary.reason_code,
                duration_sec=summary.duration_sec,
                execution_mode_used=summary.execution_mode_used,
                cases_detail=_cases_detail_from_metrics(summary.score.metrics),
            )
            for summary in summaries
        ],
    )


def _elapsed_seconds(*, runtime: StageRuntimePaths, workflow_run_id: str) -> int | None:
    metadata = load_optional_reporting_metadata(stage_root=runtime.stage_root, workflow_run_id=workflow_run_id)
    if metadata is None or not metadata.started_at:
        return None
    try:
        started_at = whenever.Instant.parse_iso(metadata.started_at)
    except ValueError:
        return None
    return max(0, int(whenever.Instant.now().timestamp() - started_at.timestamp()))


def _resolved_logs_dir_under_stage(stage_root: Path, logs_uri: str) -> Path | None:
    """Return the logs directory if it exists and stays under ``stage_root``; else None."""
    if not logs_uri.strip():
        return None
    base = stage_root.resolve()
    try:
        candidate = (stage_root / logs_uri).resolve()
    except (OSError, RuntimeError):
        return None
    if not candidate.is_relative_to(base):
        return None
    if not candidate.is_dir():
        return None
    return candidate


def _append_leg_log_files_to_dump(dump_lines: list[str], summary: LegSummary, logs_root: Path) -> None:
    for log_file in sorted(logs_root.rglob("*")):
        if not log_file.is_file():
            continue
        dump_lines.append(f"===== {summary.project}/{summary.bmt_slug}: {log_file.name} =====")
        dump_lines.append(log_file.read_text(encoding="utf-8", errors="replace"))
        dump_lines.append("")


def _write_log_dump_and_sign(
    *, plan: ExecutionPlan, runtime: StageRuntimePaths, summaries: list[LegSummary]
) -> str | None:
    if aggregate_status(summaries) == BmtLegStatus.PASS.value:
        return None
    dump_lines: list[str] = []
    for summary in summaries:
        if leg_status_is_pass(summary.status) or not summary.logs_uri:
            continue
        logs_root = _resolved_logs_dir_under_stage(runtime.stage_root, summary.logs_uri)
        if logs_root is None:
            continue
        _append_leg_log_files_to_dump(dump_lines, summary, logs_root)
    if not dump_lines:
        return None
    relative_path = f"log-dumps/{plan.workflow_run_id}.txt"
    dump_path = runtime.stage_root / relative_path
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dump_path.write_text("\n".join(dump_lines), encoding="utf-8")
    bucket_name = (os.environ.get(ENV_GCS_BUCKET) or "").strip()
    if not bucket_name:
        return None
    return _generate_signed_url(bucket_name=bucket_name, blob_name=relative_path)


def _generate_signed_url(*, bucket_name: str, blob_name: str) -> str | None:
    try:
        credentials, _ = google.auth.default()
        credentials.refresh(Request())
        service_account_email = getattr(credentials, "service_account_email", "")
        if not service_account_email or not getattr(credentials, "token", ""):
            return None
        client = gcs_storage.Client()
        blob = client.bucket(bucket_name).blob(blob_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=3),
            method="GET",
            service_account_email=service_account_email,
            access_token=credentials.token,
        )
    except (google_api_exceptions.GoogleAPIError, google_auth_exceptions.GoogleAuthError):
        logger.warning("generate_signed_url failed bucket=%s blob=%s", bucket_name, blob_name, exc_info=True)
        return None

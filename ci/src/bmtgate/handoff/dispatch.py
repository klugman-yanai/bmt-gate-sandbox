"""Direct GitHub -> Workflows handoff for the Cloud Run BMT pipeline."""

from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from whenever import Instant

from bmtgate import core
from bmtgate import settings as config
from bmtgate.clients.actions import gh_warning, write_github_output
from bmtgate.clients.cloud_run import CloudRunJobsApiError, run_job
from bmtgate.clients.gcs import delete_object, download_json, upload_json
from bmtgate.clients.workflows import WorkflowsApiError, cancel_execution, start_execution
from bmtgate.contract.constants import (
    BMT_WORKFLOW_RUN_ID_ENV,
    DEFAULT_WORKFLOW_NAME,
    ENV_BMT_CONTROL_JOB,
    ENV_BMT_FAILURE_REASON,
    ENV_BMT_FINALIZE_HEAD_SHA,
    ENV_BMT_FINALIZE_PR_NUMBER,
    ENV_BMT_FINALIZE_REPOSITORY,
    ENV_BMT_GCS_BUCKET_NAME,
    ENV_BMT_HANDOFF_RUN_URL,
    ENV_BMT_STATUS_CONTEXT,
    ENV_GCP_PROJECT,
    ENV_GCS_BUCKET,
)
from bmtgate.contract.env_parse import is_truthy_env_value
from bmtgate.contract.gcp_links import workflow_execution_console_url
from bmtgate.settings import BmtConfig


class WorkflowDispatchInvokePayload(TypedDict):
    """JSON-serializable argument passed to Workflows ``start_execution`` for BMT handoff."""

    workflow_run_id: str
    bucket: str
    repository: str
    head_sha: str
    head_branch: str
    head_event: str
    pr_number: str
    run_context: str
    accepted_projects: list[str]
    accepted_projects_json: str
    status_context: str
    use_mock_runner: bool
    use_mock_runner_str: str
    github_handoff_run_url: str


def _github_handoff_run_url() -> str:
    repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    rid = (os.environ.get("GITHUB_RUN_ID") or "").strip()
    server = (os.environ.get("GITHUB_SERVER_URL") or "https://github.com").strip().rstrip("/")
    if not repo or not rid:
        return ""
    return f"{server}/{repo}/actions/runs/{rid}"


def _accepted_projects(filtered_matrix_json: str) -> list[str]:
    payload = json.loads(filtered_matrix_json)
    include = payload.get("include", [])
    if not isinstance(include, list):
        raise RuntimeError("FILTERED_MATRIX_JSON must contain an 'include' array")
    accepted: list[str] = []
    seen: set[str] = set()
    for row in include:
        if not isinstance(row, dict):
            continue
        project = str(row.get("project", "")).strip()
        if project and project not in seen:
            seen.add(project)
            accepted.append(project)
    return accepted


class WorkflowDispatchManager:
    def __init__(self, cfg: BmtConfig) -> None:
        self._cfg = cfg

    @classmethod
    def from_env(cls) -> WorkflowDispatchManager:
        return cls(config.get_config())

    def invoke(self) -> None:
        cfg = self._cfg
        github_output = core.require_env("GITHUB_OUTPUT")
        filtered_matrix_json = core.require_env("FILTERED_MATRIX_JSON")
        accepted_projects = _accepted_projects(filtered_matrix_json)
        if not accepted_projects:
            raise RuntimeError("No accepted projects were present in FILTERED_MATRIX_JSON")

        pr_number = (os.environ.get("PR_NUMBER") or "").strip()
        repository = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
        new_workflow_run_id = core.workflow_run_id()
        self._cancel_superseded_pr_workflow_if_any(
            pr_number=pr_number,
            repository=repository,
            new_workflow_run_id=new_workflow_run_id,
        )

        # Mock runner is off unless CI explicitly sets BMT_USE_MOCK_RUNNER (see bmt-handoff.yml).
        use_mock = is_truthy_env_value(os.environ.get("BMT_USE_MOCK_RUNNER"))
        payload: WorkflowDispatchInvokePayload = {
            "workflow_run_id": new_workflow_run_id,
            "bucket": cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET),
            "repository": repository,
            "head_sha": (os.environ.get("HEAD_SHA") or "").strip(),
            "head_branch": (os.environ.get("HEAD_BRANCH") or "").strip(),
            "head_event": (os.environ.get("HEAD_EVENT") or "push").strip(),
            "pr_number": pr_number,
            "run_context": (os.environ.get("RUN_CONTEXT") or "ci").strip(),
            "accepted_projects": accepted_projects,
            "accepted_projects_json": json.dumps(accepted_projects, separators=(",", ":")),
            "status_context": cfg.bmt_status_context,
            "use_mock_runner": use_mock,
            "use_mock_runner_str": "true" if use_mock else "false",
            "github_handoff_run_url": _github_handoff_run_url(),
        }
        execution = start_execution(
            project=cfg.gcp_project or core.require_env(ENV_GCP_PROJECT),
            region=cfg.cloud_run_region,
            workflow_name=DEFAULT_WORKFLOW_NAME,
            argument=payload,
        )
        execution_name = str(execution.get("name") or "").strip()
        execution_state = str(execution.get("state") or "").strip()
        if not execution_name:
            raise RuntimeError("Workflow execution response did not include a name")
        execution_url = workflow_execution_console_url(
            project=cfg.gcp_project or core.require_env(ENV_GCP_PROJECT),
            region=cfg.cloud_run_region,
            workflow_name=DEFAULT_WORKFLOW_NAME,
            execution_name=execution_name,
        )
        self._write_pr_active_execution(
            pr_number=payload["pr_number"],
            repository=payload["repository"],
            head_sha=payload["head_sha"],
            workflow_execution_name=execution_name,
            workflow_execution_url=execution_url,
            github_handoff_run_url=payload["github_handoff_run_url"],
        )

        write_github_output(
            github_output, "accepted_projects", json.dumps(accepted_projects, separators=(",", ":"))
        )
        write_github_output(github_output, "workflow_execution_name", execution_name)
        write_github_output(github_output, "workflow_execution_url", execution_url)
        write_github_output(github_output, "workflow_execution_state", execution_state or "UNKNOWN")
        write_github_output(github_output, "dispatch_confirmed", "true")
        write_github_output(github_output, "dispatch_reason", "ok_workflow_execution_started")

    def cancel_pr_execution(self) -> None:
        cfg = self._cfg
        github_output = core.require_env("GITHUB_OUTPUT")
        repository = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
        pr_number = (os.environ.get("PR_NUMBER") or "").strip()
        head_sha = (os.environ.get("HEAD_SHA") or "").strip()
        if not repository:
            raise RuntimeError("GITHUB_REPOSITORY is required")
        if not pr_number.isdigit():
            raise RuntimeError("PR_NUMBER must be a numeric pull request number")

        index_uri = _pr_active_execution_uri(
            bucket=cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET), pr_number=pr_number
        )
        payload, error = download_json(index_uri)
        if payload is None:
            write_github_output(github_output, "cancel_requested", "false")
            write_github_output(
                github_output, "cancel_reason", f"no_active_execution:{error or 'missing'}"
            )
            write_github_output(github_output, "finalize_requested", "false")
            write_github_output(github_output, "finalize_outcome", "skipped_no_active_execution")
            return

        indexed_repo = str(payload.get("repository") or "").strip()
        if indexed_repo and indexed_repo != repository:
            write_github_output(github_output, "cancel_requested", "false")
            write_github_output(github_output, "cancel_reason", "repository_mismatch")
            write_github_output(github_output, "finalize_requested", "false")
            write_github_output(github_output, "finalize_outcome", "skipped_repository_mismatch")
            return

        indexed_head_sha = str(payload.get("head_sha") or "").strip()
        if head_sha and indexed_head_sha and indexed_head_sha != head_sha:
            gh_warning(
                "PR close cancel: head_sha mismatch (continuing with index execution): "
                f"index={indexed_head_sha!r} event={head_sha!r}"
            )

        execution_name = str(payload.get("workflow_execution_name") or "").strip()
        if not execution_name:
            write_github_output(github_output, "cancel_requested", "false")
            write_github_output(github_output, "cancel_reason", "missing_execution_name")
            write_github_output(github_output, "finalize_requested", "false")
            write_github_output(github_output, "finalize_outcome", "skipped_missing_execution_name")
            return

        workflow_run_id = str(payload.get("workflow_run_id") or "").strip()

        try:
            cancel_execution(execution_name=execution_name)
        except WorkflowsApiError as exc:
            write_github_output(github_output, "cancel_requested", "false")
            write_github_output(github_output, "cancel_reason", f"cancel_failed:{exc}")
            write_github_output(github_output, "finalize_requested", "false")
            write_github_output(github_output, "finalize_outcome", "skipped_cancel_failed")
            return

        delete_object(index_uri)
        write_github_output(github_output, "cancel_requested", "true")
        write_github_output(github_output, "cancel_reason", "cancel_requested")
        write_github_output(github_output, "cancelled_execution_name", execution_name)

        if not workflow_run_id:
            write_github_output(github_output, "finalize_requested", "false")
            write_github_output(github_output, "finalize_outcome", "skipped_no_workflow_run_id")
            return

        job_name = (cfg.bmt_control_job or "").strip() or (
            os.environ.get(ENV_BMT_CONTROL_JOB) or ""
        ).strip()
        if not job_name:
            write_github_output(github_output, "finalize_requested", "false")
            write_github_output(github_output, "finalize_outcome", "skipped_no_bmt_control_job")
            return

        reason = (os.environ.get(ENV_BMT_FAILURE_REASON) or "").strip() or (
            "PR closed before BMT finished; workflow execution was cancelled."
        )
        status_ctx = (
            cfg.bmt_status_context or os.environ.get(ENV_BMT_STATUS_CONTEXT) or ""
        ).strip()
        bucket = cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET)
        handoff_url = str(payload.get("github_handoff_run_url") or "").strip()
        try:
            run_job(
                project=cfg.gcp_project or core.require_env(ENV_GCP_PROJECT),
                region=cfg.cloud_run_region,
                job_name=job_name,
                env_vars={
                    "BMT_MODE": "finalize-failure",
                    BMT_WORKFLOW_RUN_ID_ENV: workflow_run_id,
                    ENV_BMT_FAILURE_REASON: reason[:500],
                    # So ``finalize-failure`` can close the GitHub Check even if ``triggers/plans/`` was
                    # never written (plan job not reached before cancel).
                    ENV_BMT_FINALIZE_REPOSITORY: repository,
                    ENV_BMT_FINALIZE_HEAD_SHA: indexed_head_sha or head_sha,
                    ENV_BMT_FINALIZE_PR_NUMBER: pr_number,
                    ENV_BMT_GCS_BUCKET_NAME: bucket,
                    **({ENV_BMT_HANDOFF_RUN_URL: handoff_url} if handoff_url else {}),
                    **({ENV_BMT_STATUS_CONTEXT: status_ctx} if status_ctx else {}),
                },
                task_count=1,
                wait=True,
                timeout_sec=900,
            )
        except CloudRunJobsApiError as exc:
            write_github_output(github_output, "finalize_requested", "true")
            write_github_output(github_output, "finalize_outcome", f"failed:{exc}")
            return

        write_github_output(github_output, "finalize_requested", "true")
        write_github_output(github_output, "finalize_outcome", "success")

    def _cancel_superseded_pr_workflow_if_any(
        self,
        *,
        pr_number: str,
        repository: str,
        new_workflow_run_id: str,
    ) -> None:
        """Cancel a prior Google Workflow execution still indexed for this PR before a new dispatch.

        GitHub Actions ``cancel-in-progress`` stops the previous handoff job but does not cancel
        the Cloud Workflow; overwriting ``pr-active`` alone would orphan the old execution.
        """
        if not pr_number.isdigit() or not repository:
            return
        cfg = self._cfg
        uri = _pr_active_execution_uri(
            bucket=cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET), pr_number=pr_number
        )
        payload, _err = download_json(uri)
        if payload is None:
            return
        indexed_repo = str(payload.get("repository") or "").strip()
        if indexed_repo and indexed_repo != repository:
            return
        old_name = str(payload.get("workflow_execution_name") or "").strip()
        old_wid = str(payload.get("workflow_run_id") or "").strip()
        if not old_name:
            return
        if old_wid == new_workflow_run_id:
            return
        try:
            cancel_execution(execution_name=old_name)
        except WorkflowsApiError as exc:
            gh_warning(
                "Supersede handoff: could not cancel prior workflow execution "
                f"({exc!r}); continuing with new dispatch."
            )

    def _write_pr_active_execution(
        self,
        *,
        pr_number: str,
        repository: str,
        head_sha: str,
        workflow_execution_name: str,
        workflow_execution_url: str,
        github_handoff_run_url: str,
    ) -> None:
        if not pr_number.isdigit() or not repository:
            return
        cfg = self._cfg
        uri = _pr_active_execution_uri(
            bucket=cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET), pr_number=pr_number
        )
        payload: dict[str, Any] = {
            "repository": repository,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "workflow_execution_name": workflow_execution_name,
            "workflow_execution_url": workflow_execution_url.strip(),
            "github_handoff_run_url": github_handoff_run_url.strip(),
            "updated_at": Instant.now().format_iso(unit="second"),
            "workflow_run_id": core.workflow_run_id(),
        }
        upload_json(uri, payload)


def _pr_active_execution_uri(*, bucket: str, pr_number: str) -> str:
    return f"gs://{bucket}/triggers/reporting/pr-active/{pr_number}.json"

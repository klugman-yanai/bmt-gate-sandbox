"""Direct GitHub -> Workflows handoff for the Cloud Run BMT pipeline."""

from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from gcp.image.config.constants import (
    BMT_WORKFLOW_RUN_ID_ENV,
    DEFAULT_WORKFLOW_NAME,
    ENV_BMT_CONTROL_JOB,
    ENV_BMT_FAILURE_REASON,
    ENV_GCP_PROJECT,
    ENV_GCS_BUCKET,
)
from gcp.image.config.env_parse import is_truthy_env_value
from gcp.image.github.reporting import workflow_execution_console_url
from whenever import Instant

from ci import config, core
from ci.actions import write_github_output
from ci.cloud_run_api import CloudRunJobsApiError, run_job
from ci.config import BmtConfig
from ci.gcs import delete_object, download_json, upload_json
from ci.workflows_api import WorkflowsApiError, cancel_execution, start_execution


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

        # Mock runner is off unless CI explicitly sets BMT_USE_MOCK_RUNNER (see bmt-handoff.yml).
        use_mock = is_truthy_env_value(os.environ.get("BMT_USE_MOCK_RUNNER"))
        payload: WorkflowDispatchInvokePayload = {
            "workflow_run_id": core.workflow_run_id(),
            "bucket": cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET),
            "repository": (os.environ.get("GITHUB_REPOSITORY") or "").strip(),
            "head_sha": (os.environ.get("HEAD_SHA") or "").strip(),
            "head_branch": (os.environ.get("HEAD_BRANCH") or "").strip(),
            "head_event": (os.environ.get("HEAD_EVENT") or "push").strip(),
            "pr_number": (os.environ.get("PR_NUMBER") or "").strip(),
            "run_context": (os.environ.get("RUN_CONTEXT") or "ci").strip(),
            "accepted_projects": accepted_projects,
            "accepted_projects_json": json.dumps(accepted_projects, separators=(",", ":")),
            "status_context": cfg.bmt_status_context,
            "use_mock_runner": use_mock,
            "use_mock_runner_str": "true" if use_mock else "false",
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

        index_uri = _pr_active_execution_uri(bucket=cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET), pr_number=pr_number)
        payload, error = download_json(index_uri)
        if payload is None:
            write_github_output(github_output, "cancel_requested", "false")
            write_github_output(github_output, "cancel_reason", f"no_active_execution:{error or 'missing'}")
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
            write_github_output(github_output, "cancel_requested", "false")
            write_github_output(github_output, "cancel_reason", "head_sha_mismatch")
            write_github_output(github_output, "finalize_requested", "false")
            write_github_output(github_output, "finalize_outcome", "skipped_head_sha_mismatch")
            return

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
        try:
            run_job(
                project=cfg.gcp_project or core.require_env(ENV_GCP_PROJECT),
                region=cfg.cloud_run_region,
                job_name=job_name,
                env_vars={
                    "BMT_MODE": "finalize-failure",
                    BMT_WORKFLOW_RUN_ID_ENV: workflow_run_id,
                    ENV_BMT_FAILURE_REASON: reason[:500],
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

    def _write_pr_active_execution(
        self,
        *,
        pr_number: str,
        repository: str,
        head_sha: str,
        workflow_execution_name: str,
    ) -> None:
        if not pr_number.isdigit() or not repository:
            return
        cfg = self._cfg
        uri = _pr_active_execution_uri(bucket=cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET), pr_number=pr_number)
        payload: dict[str, Any] = {
            "repository": repository,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "workflow_execution_name": workflow_execution_name,
            "updated_at": Instant.now().format_iso(unit="second"),
            "workflow_run_id": core.workflow_run_id(),
        }
        upload_json(uri, payload)


def _pr_active_execution_uri(*, bucket: str, pr_number: str) -> str:
    return f"gs://{bucket}/triggers/reporting/pr-active/{pr_number}.json"

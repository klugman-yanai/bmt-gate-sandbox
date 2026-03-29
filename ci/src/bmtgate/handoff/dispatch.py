"""Direct GitHub -> Workflows handoff for the Cloud Run BMT pipeline."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, TypedDict

from bmtcontract.models import DispatchReceiptState, DispatchReceiptV1
from bmtcontract.paths import dispatch_receipt_path, pr_active_execution_path
from pydantic import ValidationError
from whenever import Instant

from bmtgate import core
from bmtgate import settings as config
from bmtgate.clients.actions import gh_warning, write_github_output
from bmtgate.clients.cloud_run import CloudRunJobsApiError, run_job
from bmtgate.clients.gcs import (
    GcsError,
    create_json_if_absent,
    delete_object,
    download_json,
    upload_json,
)
from bmtgate.clients.workflows import WorkflowsApiError, cancel_execution, start_execution
from bmtgate.contract.constants import (
    BMT_WORKFLOW_RUN_ID_ENV,
    DEFAULT_WORKFLOW_NAME,
    ENV_BMT_ALLOW_UNSAFE_SUPERSEDE,
    ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK,
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

logger = logging.getLogger(__name__)
_SUPERSEDE_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 3.0)


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


def _sleep_before_retry(*, attempt: int, max_attempts: int) -> None:
    if attempt >= max_attempts:
        return
    delay = _SUPERSEDE_RETRY_BACKOFF_SECONDS[min(attempt - 1, len(_SUPERSEDE_RETRY_BACKOFF_SECONDS) - 1)]
    time.sleep(delay)


def _strict_supersede_required() -> bool:
    raw_require_cancel = os.environ.get(ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK)
    if raw_require_cancel is not None:
        return is_truthy_env_value(raw_require_cancel)
    raw_allow_unsafe = os.environ.get(ENV_BMT_ALLOW_UNSAFE_SUPERSEDE)
    if raw_allow_unsafe is not None:
        return not is_truthy_env_value(raw_allow_unsafe)
    return False


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
        require_cancel_ok = _strict_supersede_required()
        cancel_ok = self._cancel_superseded_pr_workflow_if_any(
            pr_number=pr_number,
            repository=repository,
            new_workflow_run_id=new_workflow_run_id,
            require_cancel_ok=require_cancel_ok,
        )
        if not cancel_ok:
            raise RuntimeError(
                "Supersede handoff: failed to cancel prior workflow execution and "
                f"{ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK}=true requires aborting dispatch."
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
        execution_name, execution_url, execution_state = self._dispatch_or_reuse_execution(
            payload=payload,
            project=cfg.gcp_project or core.require_env(ENV_GCP_PROJECT),
            region=cfg.cloud_run_region,
            workflow_name=DEFAULT_WORKFLOW_NAME,
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
        require_cancel_ok: bool,
    ) -> bool:
        """Cancel a prior Google Workflow execution still indexed for this PR before a new dispatch.

        GitHub Actions ``cancel-in-progress`` stops the previous handoff job but does not cancel
        the Cloud Workflow; overwriting ``pr-active`` alone would orphan the old execution.
        """
        if not pr_number.isdigit() or not repository:
            return True
        cfg = self._cfg
        uri = _pr_active_execution_uri(
            bucket=cfg.gcs_bucket or core.require_env(ENV_GCS_BUCKET), pr_number=pr_number
        )
        payload, _err = download_json(uri)
        if payload is None:
            return True
        indexed_repo = str(payload.get("repository") or "").strip()
        if indexed_repo and indexed_repo != repository:
            return True
        old_name = str(payload.get("workflow_execution_name") or "").strip()
        old_wid = str(payload.get("workflow_run_id") or "").strip()
        if not old_name:
            return True
        if old_wid == new_workflow_run_id:
            return True
        max_attempts = len(_SUPERSEDE_RETRY_BACKOFF_SECONDS) + 1
        last_error: WorkflowsApiError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                cancel_execution(execution_name=old_name)
                return True
            except WorkflowsApiError as exc:
                last_error = exc
                if attempt < max_attempts:
                    _sleep_before_retry(attempt=attempt, max_attempts=max_attempts)
                    continue
        log_message = (
            "supersede cancel exhausted repository=%s pr_number=%s old_execution_name=%s "
            "old_workflow_run_id=%s new_workflow_run_id=%s strict_mode=%s"
        )
        if require_cancel_ok:
            logger.error(
                log_message,
                repository,
                pr_number,
                old_name,
                old_wid,
                new_workflow_run_id,
                require_cancel_ok,
                exc_info=last_error,
            )
            gh_warning(
                "Supersede handoff: could not cancel prior workflow execution after retries; "
                f"aborting dispatch because {ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK}=true."
            )
            return False
        logger.warning(
            log_message,
            repository,
            pr_number,
            old_name,
            old_wid,
            new_workflow_run_id,
            require_cancel_ok,
            exc_info=last_error,
        )
        gh_warning(
            "Supersede handoff: could not cancel prior workflow execution after retries; "
            "continuing with new dispatch."
        )
        return True

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

    def _dispatch_or_reuse_execution(
        self,
        *,
        payload: WorkflowDispatchInvokePayload,
        project: str,
        region: str,
        workflow_name: str,
    ) -> tuple[str, str, str]:
        receipt_uri = _dispatch_receipt_uri(bucket=payload["bucket"], workflow_run_id=payload["workflow_run_id"])
        receipt = self._load_or_claim_dispatch_receipt(
            uri=receipt_uri,
            workflow_run_id=payload["workflow_run_id"],
            repository=payload["repository"],
            head_sha=payload["head_sha"],
        )
        if receipt.state == DispatchReceiptState.STARTED:
            execution_name = receipt.workflow_execution_name.strip()
            if not execution_name:
                raise RuntimeError(f"Dispatch receipt {receipt_uri} is started but missing workflow_execution_name")
            execution_url = receipt.workflow_execution_url.strip() or workflow_execution_console_url(
                project=project,
                region=region,
                workflow_name=workflow_name,
                execution_name=execution_name,
            )
            execution_state = receipt.workflow_execution_state.strip() or "UNKNOWN"
            return execution_name, execution_url, execution_state

        try:
            execution = start_execution(
                project=project,
                region=region,
                workflow_name=workflow_name,
                argument=payload,
            )
        except WorkflowsApiError as exc:
            self._persist_dispatch_receipt(
                uri=receipt_uri,
                receipt=receipt.model_copy(
                    update={
                        "state": DispatchReceiptState.START_FAILED,
                        "updated_at": Instant.now().format_iso(unit="second"),
                        "error_message": str(exc),
                    }
                ),
            )
            raise

        execution_name = str(execution.get("name") or "").strip()
        execution_state = str(execution.get("state") or "").strip()
        if not execution_name:
            raise RuntimeError("Workflow execution response did not include a name")
        execution_url = workflow_execution_console_url(
            project=project,
            region=region,
            workflow_name=workflow_name,
            execution_name=execution_name,
        )
        self._persist_dispatch_receipt(
            uri=receipt_uri,
            receipt=receipt.model_copy(
                update={
                    "state": DispatchReceiptState.STARTED,
                    "updated_at": Instant.now().format_iso(unit="second"),
                    "workflow_execution_name": execution_name,
                    "workflow_execution_url": execution_url,
                    "workflow_execution_state": execution_state,
                    "error_message": "",
                }
            ),
        )
        return execution_name, execution_url, execution_state

    def _load_or_claim_dispatch_receipt(
        self,
        *,
        uri: str,
        workflow_run_id: str,
        repository: str,
        head_sha: str,
    ) -> DispatchReceiptV1:
        now_iso = Instant.now().format_iso(unit="second")
        receipt = DispatchReceiptV1(
            workflow_run_id=workflow_run_id,
            repository=repository,
            head_sha=head_sha,
            state=DispatchReceiptState.PENDING_START,
            created_at=now_iso,
            updated_at=now_iso,
        )
        try:
            if create_json_if_absent(uri, receipt.model_dump(mode="json")):
                return receipt
        except GcsError as exc:
            raise RuntimeError(f"Failed to create dispatch receipt {uri}: {exc}") from exc

        payload, error = download_json(uri)
        if payload is None:
            raise RuntimeError(f"Dispatch receipt {uri} could not be loaded: {error or 'missing'}")
        try:
            existing = DispatchReceiptV1.model_validate(payload)
        except ValidationError as exc:
            raise RuntimeError(f"Dispatch receipt {uri} is invalid: {exc}") from exc
        if existing.repository != repository or existing.head_sha != head_sha:
            raise RuntimeError(
                "Dispatch receipt workflow_run_id conflict: existing receipt has different repository or head_sha"
            )
        return existing

    def _persist_dispatch_receipt(self, *, uri: str, receipt: DispatchReceiptV1) -> None:
        try:
            upload_json(uri, receipt.model_dump(mode="json"))
        except GcsError as exc:
            raise RuntimeError(f"Failed to update dispatch receipt {uri}: {exc}") from exc


def _pr_active_execution_uri(*, bucket: str, pr_number: str) -> str:
    return f"gs://{bucket}/{pr_active_execution_path(pr_number)}"


def _dispatch_receipt_uri(*, bucket: str, workflow_run_id: str) -> str:
    return f"gs://{bucket}/{dispatch_receipt_path(workflow_run_id)}"

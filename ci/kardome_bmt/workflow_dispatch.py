"""Direct GitHub -> Workflows handoff for the Cloud Run BMT pipeline."""

from __future__ import annotations

import json
import os
from typing import TypedDict

from runtime.config.constants import DEFAULT_WORKFLOW_NAME, ENV_GCP_PROJECT, ENV_GCS_BUCKET
from runtime.github.reporting import workflow_execution_console_url

from kardome_bmt import config, core
from kardome_bmt.actions import gh_warning, write_github_output
from kardome_bmt.config import BmtConfig
from kardome_bmt.workflows_api import start_execution


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


def _accepted_projects(filtered_matrix_json: str) -> list[str]:
    payload = json.loads(filtered_matrix_json)
    include = payload.get("include", [])
    if not isinstance(include, list):
        raise TypeError("FILTERED_MATRIX_JSON must contain an 'include' array")
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

    def invoke(self, *, force_pass: bool = False) -> None:
        cfg = self._cfg
        github_output = core.require_env("GITHUB_OUTPUT")
        filtered_matrix_json = core.require_env("FILTERED_MATRIX_JSON")
        accepted_projects = _accepted_projects(filtered_matrix_json)
        if not accepted_projects:
            raise RuntimeError("No accepted projects were present in FILTERED_MATRIX_JSON")

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
        }
        try:
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

            write_github_output(
                github_output, "accepted_projects", json.dumps(accepted_projects, separators=(",", ":"))
            )
            write_github_output(github_output, "workflow_execution_name", execution_name)
            write_github_output(github_output, "workflow_execution_url", execution_url)
            write_github_output(github_output, "workflow_execution_state", execution_state or "UNKNOWN")
            write_github_output(github_output, "dispatch_confirmed", "true")
            write_github_output(github_output, "dispatch_reason", "ok_workflow_execution_started")
        except Exception as exc:
            if not force_pass:
                raise
            gh_warning(
                "BMT_FORCE_PASS / --force-pass: dispatch failed but exiting 0 so the Actions step "
                f"succeeds. Error was: {exc}"
            )
            write_github_output(
                github_output, "accepted_projects", json.dumps(accepted_projects, separators=(",", ":"))
            )
            write_github_output(github_output, "workflow_execution_name", "")
            write_github_output(github_output, "workflow_execution_url", "")
            write_github_output(github_output, "workflow_execution_state", "FORCED_PASS_NOT_DISPATCHED")
            write_github_output(github_output, "dispatch_confirmed", "false")
            write_github_output(github_output, "dispatch_reason", "bmt_force_pass_suppressed_error")

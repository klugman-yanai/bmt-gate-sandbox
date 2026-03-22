"""Authorized REST helpers for Workflows and Cloud Run Jobs."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class GoogleApiError(RuntimeError):
    """Raised when a Google API request fails."""


def _session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    if not credentials.valid:
        credentials.refresh(Request())
    return AuthorizedSession(credentials)


def _raise_for_response(*, method: str, url: str, response) -> None:
    if response.ok:
        return
    detail = response.text
    raise GoogleApiError(f"{method} {url} failed: {response.status_code} {detail}")


def invoke_workflow_execution(
    *,
    project: str,
    region: str,
    workflow_name: str,
    argument: Mapping[str, Any],
) -> dict[str, Any]:
    session = _session()
    url = (
        "https://workflowexecutions.googleapis.com/v1/"
        f"projects/{project}/locations/{region}/workflows/{workflow_name}/executions"
    )
    response = session.post(url, json={"argument": json.dumps(argument, separators=(",", ":"))}, timeout=60)
    _raise_for_response(method="POST", url=url, response=response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise GoogleApiError("Workflow execution response was not a JSON object")
    return payload


def run_cloud_run_job(
    *,
    project: str,
    region: str,
    job_name: str,
    env_vars: Mapping[str, str] | None = None,
    task_count: int | None = None,
    wait: bool = True,
    poll_interval_sec: float = 5.0,
    timeout_sec: int = 3600,
) -> dict[str, Any]:
    session = _session()
    url = f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job_name}:run"
    overrides: dict[str, Any] = {}
    if task_count is not None:
        overrides["taskCount"] = task_count
    if env_vars:
        overrides["containerOverrides"] = [
            {
                "env": [{"name": key, "value": value} for key, value in sorted(env_vars.items())],
            }
        ]
    body = {"overrides": overrides} if overrides else {}
    response = session.post(url, json=body, timeout=60)
    _raise_for_response(method="POST", url=url, response=response)
    payload = response.json()
    if not wait:
        return payload
    operation_name = payload.get("name")
    if not isinstance(operation_name, str) or not operation_name:
        raise GoogleApiError("Cloud Run Jobs run response did not include an operation name")
    from tools.shared.rich_minimal import spinner_status, step_console

    deadline = time.monotonic() + timeout_sec
    operation_url = f"https://run.googleapis.com/v2/{operation_name}"
    console = step_console()
    with spinner_status(console, f"Cloud Run job {job_name!r} running…"):
        while True:
            poll_response = session.get(operation_url, timeout=60)
            _raise_for_response(method="GET", url=operation_url, response=poll_response)
            operation_payload = poll_response.json()
            if bool(operation_payload.get("done")):
                if "error" in operation_payload:
                    raise GoogleApiError(f"Cloud Run job {job_name} failed: {operation_payload['error']}")
                return operation_payload
            if time.monotonic() >= deadline:
                raise GoogleApiError(f"Timed out waiting for Cloud Run job {job_name} to finish")
            time.sleep(poll_interval_sec)

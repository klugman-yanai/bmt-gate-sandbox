"""Cloud Run Jobs v2 REST helpers (minimal; no Rich/console)."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class CloudRunJobsApiError(RuntimeError):
    """Raised when a Cloud Run Jobs API request fails."""


def _session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    if not credentials.valid:
        credentials.refresh(Request())
    return AuthorizedSession(credentials)


def _raise_for_response(*, method: str, url: str, response) -> None:
    if response.ok:
        return
    raise CloudRunJobsApiError(f"{method} {url} failed: {response.status_code} {response.text}")


def run_job(
    *,
    project: str,
    region: str,
    job_name: str,
    env_vars: Mapping[str, str] | None = None,
    task_count: int | None = None,
    wait: bool = True,
    poll_interval_sec: float = 5.0,
    timeout_sec: int = 900,
) -> dict[str, Any]:
    """Start a Cloud Run Job execution; optionally wait for the LRO to complete."""
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
    if not isinstance(payload, dict):
        raise CloudRunJobsApiError("Cloud Run Jobs run response was not a JSON object")
    if not wait:
        return payload
    operation_name = payload.get("name")
    if not isinstance(operation_name, str) or not operation_name:
        raise CloudRunJobsApiError("Cloud Run Jobs run response did not include an operation name")
    deadline = time.monotonic() + timeout_sec
    operation_url = f"https://run.googleapis.com/v2/{operation_name}"
    while True:
        poll_response = session.get(operation_url, timeout=60)
        _raise_for_response(method="GET", url=operation_url, response=poll_response)
        operation_payload = poll_response.json()
        if bool(operation_payload.get("done")):
            if "error" in operation_payload:
                raise CloudRunJobsApiError(f"Cloud Run job {job_name} failed: {operation_payload['error']}")
            return operation_payload
        if time.monotonic() >= deadline:
            raise CloudRunJobsApiError(f"Timed out waiting for Cloud Run job {job_name} to finish")
        time.sleep(poll_interval_sec)

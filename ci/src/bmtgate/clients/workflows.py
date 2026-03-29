"""Direct Workflow Executions API helpers."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import google.auth
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import AuthorizedSession, Request

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 3.0)


class WorkflowsApiError(RuntimeError):
    """Raised when a Cloud Workflows API request fails."""


def _session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    if not credentials.valid:
        credentials.refresh(Request())
    return AuthorizedSession(credentials)


def _sleep_before_retry(*, attempt: int, max_attempts: int) -> None:
    if attempt >= max_attempts:
        return
    delay = _RETRY_BACKOFF_SECONDS[min(attempt - 1, len(_RETRY_BACKOFF_SECONDS) - 1)]
    time.sleep(delay)


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code == 503 or 500 <= status_code < 600


def _post_json_once(*, url: str, payload: Mapping[str, Any]) -> Any:
    session = _session()
    try:
        return session.post(url, json=dict(payload), timeout=60)
    except (OSError, google_auth_exceptions.TransportError) as exc:
        raise WorkflowsApiError(f"POST {url} failed: {exc}") from exc


def _post_json_with_retry(*, url: str, payload: Mapping[str, Any]) -> Any:
    max_attempts = len(_RETRY_BACKOFF_SECONDS) + 1
    for attempt in range(1, max_attempts + 1):
        response = _post_json_once(url=url, payload=payload)
        if response.ok:
            return response
        if _is_retryable_status(response.status_code) and attempt < max_attempts:
            _sleep_before_retry(attempt=attempt, max_attempts=max_attempts)
            continue
        raise WorkflowsApiError(f"POST {url} failed: {response.status_code} {response.text}")

    raise AssertionError("unreachable")


def start_execution(
    *,
    project: str,
    region: str,
    workflow_name: str,
    argument: Mapping[str, Any],
) -> dict[str, Any]:
    url = (
        "https://workflowexecutions.googleapis.com/v1/"
        f"projects/{project}/locations/{region}/workflows/{workflow_name}/executions"
    )
    response = _post_json_with_retry(url=url, payload={"argument": json.dumps(argument, separators=(",", ":"))})
    payload = response.json()
    if not isinstance(payload, dict):
        raise WorkflowsApiError("Workflow execution response was not a JSON object")
    return payload


def cancel_execution(*, execution_name: str) -> None:
    """Cancel a running Cloud Workflow execution by full resource name."""
    name = execution_name.strip()
    if not name:
        raise WorkflowsApiError("execution_name is required")
    url = f"https://workflowexecutions.googleapis.com/v1/{name}:cancel"
    response = _post_json_once(url=url, payload={})
    if not response.ok:
        raise WorkflowsApiError(f"POST {url} failed: {response.status_code} {response.text}")

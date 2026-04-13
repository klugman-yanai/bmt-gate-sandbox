"""Direct Workflow Executions API helpers."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import google.auth
import requests.exceptions
from google.auth.transport.requests import AuthorizedSession, Request

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# HTTP status codes that are safe to retry (server explicitly declined, did not process).
_RETRYABLE_STATUSES = frozenset({429, 503})


class WorkflowsApiError(RuntimeError):
    """Raised when a Cloud Workflows API request fails."""


def _session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    if not credentials.valid:
        credentials.refresh(Request())
    return AuthorizedSession(credentials)


def start_execution(
    *,
    project: str,
    region: str,
    workflow_name: str,
    argument: Mapping[str, Any],
    _max_attempts: int = 3,
) -> dict[str, Any]:
    """POST to Workflows Executions API, with retry on 429/503/ConnectionError.

    Retryable conditions are those where the server provably did NOT start an execution:
    - ``ConnectionError``: request never reached the server.
    - HTTP 429/503: server explicitly declined with a "retry later" signal.

    NOT retried: timeout (ambiguous — server may have processed the request and started an
    execution; retrying risks a duplicate run), and all other HTTP errors.
    """
    url = (
        "https://workflowexecutions.googleapis.com/v1/"
        f"projects/{project}/locations/{region}/workflows/{workflow_name}/executions"
    )
    body = {"argument": json.dumps(argument, separators=(",", ":"))}
    last_exc: BaseException | None = None

    for attempt in range(1, _max_attempts + 1):
        try:
            response = _session().post(url, json=body, timeout=60)
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            if attempt < _max_attempts:
                time.sleep(2 ** (attempt - 1))
            continue

        if response.status_code in _RETRYABLE_STATUSES:
            last_exc = WorkflowsApiError(
                f"POST {url} transient {response.status_code} (attempt {attempt}/{_max_attempts})"
            )
            if attempt < _max_attempts:
                time.sleep(2 ** (attempt - 1))
                continue

        if not response.ok:
            raise WorkflowsApiError(f"POST {url} failed: {response.status_code} {response.text}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise WorkflowsApiError("Workflow execution response was not a JSON object")
        return payload

    raise WorkflowsApiError(
        f"POST {url} failed after {_max_attempts} attempts"
    ) from last_exc

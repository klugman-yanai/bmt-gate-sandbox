"""Direct Workflow Executions API helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


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
) -> dict[str, Any]:
    session = _session()
    url = (
        "https://workflowexecutions.googleapis.com/v1/"
        f"projects/{project}/locations/{region}/workflows/{workflow_name}/executions"
    )
    response = session.post(url, json={"argument": json.dumps(argument, separators=(",", ":"))}, timeout=60)
    if not response.ok:
        raise WorkflowsApiError(f"POST {url} failed: {response.status_code} {response.text}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise WorkflowsApiError("Workflow execution response was not a JSON object")
    return payload

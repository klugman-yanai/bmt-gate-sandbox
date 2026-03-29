from __future__ import annotations

import pytest
from bmtgate.clients import workflows
from google.auth import exceptions as google_auth_exceptions

pytestmark = pytest.mark.unit


class _FakeResponse:
    def __init__(self, *, ok: bool, status_code: int, text: str, payload: dict | None = None) -> None:
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def test_start_execution_retries_transient_http_failure(monkeypatch) -> None:
    sleeps: list[float] = []
    responses = iter(
        [
            _FakeResponse(ok=False, status_code=503, text="unavailable"),
            _FakeResponse(ok=False, status_code=429, text="rate limited"),
            _FakeResponse(ok=True, status_code=200, text="ok", payload={"name": "exec-1", "state": "ACTIVE"}),
        ]
    )

    class _FakeSession:
        def post(self, url: str, json: dict, timeout: int) -> _FakeResponse:
            _ = (url, json, timeout)
            return next(responses)

    def _session_stub() -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr("bmtgate.clients.workflows._session", _session_stub)
    monkeypatch.setattr("bmtgate.clients.workflows.time.sleep", sleeps.append)

    payload = workflows.start_execution(
        project="demo-project",
        region="europe-west4",
        workflow_name="bmt-workflow",
        argument={"workflow_run_id": "123"},
    )

    assert payload["name"] == "exec-1"
    assert sleeps == [1.0, 3.0]


def test_start_execution_does_not_retry_non_retryable_4xx(monkeypatch) -> None:
    sleeps: list[float] = []

    class _FakeSession:
        def post(self, url: str, json: dict, timeout: int) -> _FakeResponse:
            _ = (url, json, timeout)
            return _FakeResponse(ok=False, status_code=403, text="forbidden")

    def _session_stub() -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr("bmtgate.clients.workflows._session", _session_stub)
    monkeypatch.setattr("bmtgate.clients.workflows.time.sleep", sleeps.append)

    with pytest.raises(workflows.WorkflowsApiError, match="403 forbidden"):
        workflows.start_execution(
            project="demo-project",
            region="europe-west4",
            workflow_name="bmt-workflow",
            argument={"workflow_run_id": "123"},
        )

    assert sleeps == []


def test_start_execution_does_not_retry_transport_failure(monkeypatch) -> None:
    sleeps: list[float] = []
    attempts = {"count": 0}

    class _FakeSession:
        def post(self, url: str, json: dict, timeout: int) -> _FakeResponse:
            _ = (url, json, timeout)
            attempts["count"] += 1
            raise google_auth_exceptions.TransportError("network wobble")

    def _session_stub() -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr("bmtgate.clients.workflows._session", _session_stub)
    monkeypatch.setattr("bmtgate.clients.workflows.time.sleep", sleeps.append)

    with pytest.raises(workflows.WorkflowsApiError, match="network wobble"):
        workflows.start_execution(
            project="demo-project",
            region="europe-west4",
            workflow_name="bmt-workflow",
            argument={"workflow_run_id": "123"},
        )

    assert attempts["count"] == 1
    assert sleeps == []


def test_cancel_execution_does_not_retry_transport_failure(monkeypatch) -> None:
    sleeps: list[float] = []
    attempts = {"count": 0}

    class _FakeSession:
        def post(self, url: str, json: dict, timeout: int) -> _FakeResponse:
            _ = (url, json, timeout)
            attempts["count"] += 1
            raise google_auth_exceptions.TransportError("network wobble")

    def _session_stub() -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr("bmtgate.clients.workflows._session", _session_stub)
    monkeypatch.setattr("bmtgate.clients.workflows.time.sleep", sleeps.append)

    with pytest.raises(workflows.WorkflowsApiError, match="network wobble"):
        workflows.cancel_execution(execution_name="projects/p/locations/r/workflows/w/executions/ex-1")

    assert attempts["count"] == 1
    assert sleeps == []

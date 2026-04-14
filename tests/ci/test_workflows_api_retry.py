"""Tests for start_execution() retry behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests.exceptions
from ci.workflows_api import WorkflowsApiError, start_execution

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, status_code: int, json_data: object = None) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = f"status {status_code}"
        self._json = json_data or {}

    def json(self) -> object:
        return self._json


_SUCCESS = _Resp(200, {"name": "projects/p/locations/r/workflows/w/executions/abc", "state": "ACTIVE"})


def _args() -> dict:
    return dict(project="p", region="r", workflow_name="w", argument={})


def _mock_session(responses: list) -> MagicMock:
    session = MagicMock()
    session.post.side_effect = responses
    return session


def test_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = [_mock_session([_Resp(429)]), _mock_session([_Resp(429)]), _mock_session([_SUCCESS])]
    monkeypatch.setattr("ci.workflows_api._session", lambda: sessions.pop(0))
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = start_execution(**_args())
    assert result["state"] == "ACTIVE"
    assert len(sessions) == 0  # all 3 sessions consumed


def test_retries_on_503_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = [_mock_session([_Resp(503)]), _mock_session([_SUCCESS])]
    monkeypatch.setattr("ci.workflows_api._session", lambda: sessions.pop(0))
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = start_execution(**_args())
    assert result["state"] == "ACTIVE"
    assert len(sessions) == 0


def test_retries_on_connection_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0

    def _session_factory() -> MagicMock:
        nonlocal call_count
        call_count += 1
        session = MagicMock()
        if call_count < 3:
            session.post.side_effect = requests.exceptions.ConnectionError("network hiccup")
        else:
            session.post.return_value = _SUCCESS
        return session

    monkeypatch.setattr("ci.workflows_api._session", _session_factory)
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = start_execution(**_args())
    assert result["state"] == "ACTIVE"
    assert call_count == 3


def test_raises_after_exhausting_all_attempts_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ci.workflows_api._session", lambda: _mock_session([_Resp(429)]))
    monkeypatch.setattr("time.sleep", lambda _: None)

    with pytest.raises(WorkflowsApiError, match="failed after 3 attempts"):
        start_execution(**_args())


def test_raises_immediately_on_non_retryable_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = [_mock_session([_Resp(400)])]
    monkeypatch.setattr("ci.workflows_api._session", lambda: sessions.pop(0))

    with pytest.raises(WorkflowsApiError, match="400"):
        start_execution(**_args())

    assert len(sessions) == 0  # only 1 attempt


def test_does_not_retry_on_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """500 is ambiguous — execution may have started. Never retry."""
    sessions = [_mock_session([_Resp(500)])]
    monkeypatch.setattr("ci.workflows_api._session", lambda: sessions.pop(0))

    with pytest.raises(WorkflowsApiError, match="500"):
        start_execution(**_args())

    assert len(sessions) == 0

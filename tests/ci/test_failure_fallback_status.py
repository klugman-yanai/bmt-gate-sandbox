"""Unit tests for fallback terminal status emission (Python bmt post-handoff-timeout-status)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from backend.config.constants import STATUS_CONTEXT
from bmtgate.handoff.manager import HandoffManager

from tests.support.fixtures.ci import BMT_FAILURE_DESCRIPTION, mock_config, mock_github_api
from tests.support.sentinels import FAKE_REPO

__all__ = ["mock_config", "mock_github_api"]  # re-export for pytest fixture discovery

pytestmark = pytest.mark.unit

_TEST_SHA = "abc123"


def test_post_handoff_timeout_status_posts_when_not_terminal(
    monkeypatch: pytest.MonkeyPatch,
    mock_github_api: MagicMock,
    mock_config: MagicMock,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("HEAD_SHA", _TEST_SHA)
    mock_github_api.should_post_failure_status.return_value = True

    HandoffManager.from_env().post_handoff_timeout_status()

    mock_github_api.should_post_failure_status.assert_called_once_with(FAKE_REPO, _TEST_SHA, STATUS_CONTEXT)
    mock_github_api.post_commit_status.assert_called_once_with(
        FAKE_REPO, _TEST_SHA, "error", STATUS_CONTEXT, BMT_FAILURE_DESCRIPTION
    )


def test_post_handoff_timeout_status_skips_when_terminal(
    monkeypatch: pytest.MonkeyPatch,
    mock_github_api: MagicMock,
    mock_config: MagicMock,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", FAKE_REPO)
    monkeypatch.setenv("HEAD_SHA", _TEST_SHA)
    mock_github_api.should_post_failure_status.return_value = False

    HandoffManager.from_env().post_handoff_timeout_status()

    mock_github_api.should_post_failure_status.assert_called_once()
    mock_github_api.post_commit_status.assert_not_called()


def test_post_handoff_timeout_status_missing_env_skips(
    monkeypatch: pytest.MonkeyPatch,
    mock_github_api: MagicMock,
    mock_config: MagicMock,
) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("HEAD_SHA", raising=False)
    monkeypatch.delenv("REPOSITORY", raising=False)

    HandoffManager.from_env().post_handoff_timeout_status()

    mock_github_api.should_post_failure_status.assert_not_called()
    mock_github_api.post_commit_status.assert_not_called()

"""Unit tests for fallback terminal status emission (Python bmt post-handoff-timeout-status)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from ci import config, github as github_api_module
from ci.handoff import HandoffManager


@pytest.fixture
def mock_github_api(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(github_api_module, "should_post_failure_status", mock.should_post_failure_status)
    monkeypatch.setattr(github_api_module, "post_commit_status", mock.post_commit_status)
    return mock


@pytest.fixture
def mock_config(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock()
    mock.bmt_status_context = "BMT Gate"
    mock.bmt_failure_status_description = "BMT failed to complete handshake."
    monkeypatch.setattr(config, "get_config", lambda: mock)
    return mock


def test_post_handoff_timeout_status_posts_when_not_terminal(
    monkeypatch: pytest.MonkeyPatch,
    mock_github_api: MagicMock,
    mock_config: MagicMock,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("HEAD_SHA", "abc123")
    mock_github_api.should_post_failure_status.return_value = True

    HandoffManager.from_env().post_handoff_timeout_status()

    mock_github_api.should_post_failure_status.assert_called_once_with("owner/repo", "abc123", "BMT Gate")
    mock_github_api.post_commit_status.assert_called_once_with(
        "owner/repo", "abc123", "error", "BMT Gate", "BMT failed to complete handshake."
    )


def test_post_handoff_timeout_status_skips_when_terminal(
    monkeypatch: pytest.MonkeyPatch,
    mock_github_api: MagicMock,
    mock_config: MagicMock,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("HEAD_SHA", "abc123")
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

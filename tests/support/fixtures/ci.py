"""Shared pytest fixtures for CI-layer tests.

Import these fixtures in test modules or conftest.py files that need
GitHub API mocking or config mocking.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kardome_bmt import config, github as github_api_module


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

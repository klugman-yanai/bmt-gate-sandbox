"""Tests for GitHub check-run API helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runtime.github import github_checks

pytestmark = pytest.mark.unit


def test_create_check_run_requires_integer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cr = MagicMock()
    mock_cr.id = None
    mock_repo = MagicMock()
    mock_repo.create_check_run.return_value = mock_cr
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo
    monkeypatch.setattr(github_checks, "Github", MagicMock(return_value=mock_gh))

    with pytest.raises(TypeError, match="integer id"):
        github_checks.create_check_run(
            "tok",
            "o/r",
            "a" * 40,
            "BMT Gate",
            "queued",
            {"title": "t", "summary": "s"},
        )


def test_create_check_run_returns_id(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cr = MagicMock()
    mock_cr.id = 4242
    mock_repo = MagicMock()
    mock_repo.create_check_run.return_value = mock_cr
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo
    monkeypatch.setattr(github_checks, "Github", MagicMock(return_value=mock_gh))

    assert (
        github_checks.create_check_run(
            "tok",
            "o/r",
            "a" * 40,
            "BMT Gate",
            "queued",
            {"title": "t", "summary": "s"},
        )
        == 4242
    )

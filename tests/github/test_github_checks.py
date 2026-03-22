"""Tests for GitHub check-run API helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from gcp.image.github import github_checks

pytestmark = pytest.mark.unit


def test_create_check_run_requires_integer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={})

    monkeypatch.setattr(github_checks.httpx, "post", MagicMock(return_value=response))

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
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"id": 4242})

    monkeypatch.setattr(github_checks.httpx, "post", MagicMock(return_value=response))

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

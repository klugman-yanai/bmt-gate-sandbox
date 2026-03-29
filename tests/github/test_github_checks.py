"""Tests for GitHub check-run API helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from backend.config.constants import STATUS_CONTEXT
from backend.github import github_checks

from tests.support.sentinels import FAKE_REPO

pytestmark = pytest.mark.unit

_FAKE_CHECK_SHA = "a" * 40


def test_create_check_run_requires_integer_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeChecks:
        def create(self, owner: str, repo: str, *, data: dict[str, object]):
            _ = (owner, repo, data)
            return SimpleNamespace(json=lambda: {"id": None})

    monkeypatch.setattr(github_checks, "_github_repo", lambda *_: (object(), "owner", "repo"))
    monkeypatch.setattr(github_checks, "github_rest", lambda _client: SimpleNamespace(checks=_FakeChecks()))

    with pytest.raises(TypeError, match="integer id"):
        github_checks.create_check_run(
            "tok",
            FAKE_REPO,
            _FAKE_CHECK_SHA,
            STATUS_CONTEXT,
            "queued",
            {"title": "t", "summary": "s"},
        )


def test_create_check_run_returns_id(monkeypatch: pytest.MonkeyPatch) -> None:
    cap: dict[str, object] = {}

    class _FakeChecks:
        def create(self, owner: str, repo: str, *, data: dict[str, object]):
            cap["owner"] = owner
            cap["repo"] = repo
            cap["data"] = data
            return SimpleNamespace(json=lambda: {"id": 4242})

    monkeypatch.setattr(github_checks, "_github_repo", lambda *_: (object(), "owner", "repo"))
    monkeypatch.setattr(github_checks, "github_rest", lambda _client: SimpleNamespace(checks=_FakeChecks()))

    assert (
        github_checks.create_check_run(
            "tok",
            FAKE_REPO,
            _FAKE_CHECK_SHA,
            STATUS_CONTEXT,
            "queued",
            {"title": "t", "summary": "s"},
        )
        == 4242
    )
    assert cap["owner"] == "owner"
    assert cap["repo"] == "repo"
    data = cap["data"]
    assert isinstance(data, dict)
    assert data["head_sha"] == _FAKE_CHECK_SHA
    assert data["name"] == STATUS_CONTEXT

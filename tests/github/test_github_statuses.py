from __future__ import annotations

import pytest
from backend.github import statuses
from backend.github.presentation import CheckFinalView, LiveLinks
from backend.github.reporting import GitHubReporter
from github import GithubException

pytestmark = pytest.mark.unit


def test_post_commit_status_with_retry_uses_backoff_and_succeeds_on_third_attempt(monkeypatch) -> None:
    sleeps: list[float] = []
    attempts: list[tuple[str, str | None]] = []
    initial_token = "fake-token-1"

    def _fake_post(
        repository: str,
        sha: str,
        state: str,
        description: str,
        target_url: str | None,
        token: str,
        *,
        context: str,
    ) -> bool:
        _ = (repository, sha, state, description, context)
        attempts.append((token, target_url))
        return len(attempts) == 3

    refreshed: list[str] = []

    def _resolve_token(repository: str) -> str:
        refreshed.append(repository)
        return f"fake-token-{len(refreshed) + 1}"

    def _record_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("backend.github.statuses.time.sleep", _record_sleep)

    ok = statuses._post_commit_status_with_retry(
        "owner/repo",
        "a" * 40,
        "failure",
        "desc",
        "https://example.test/details",
        initial_token,
        context="BMT Gate",
        token_resolver=_resolve_token,
        _post_func=_fake_post,
    )

    assert ok is True
    assert sleeps == [1.0, 3.0]
    assert attempts == [
        ("fake-token-1", "https://example.test/details"),
        ("fake-token-2", "https://example.test/details"),
        ("fake-token-3", "https://example.test/details"),
    ]


def test_finalize_check_run_with_retry_uses_backoff_on_transient_failures(monkeypatch) -> None:
    sleeps: list[float] = []
    attempts: list[tuple[str, str | None]] = []
    initial_token = "fake-token-1"

    def _fake_update_check_run(
        token: str,
        repository: str,
        check_run_id: int,
        *,
        status: str | None = None,
        conclusion: str | None = None,
        output: dict[str, object] | None = None,
        details_url: str | None = None,
    ) -> None:
        _ = (repository, check_run_id, status, conclusion, output)
        attempts.append((token, details_url))
        if len(attempts) < 3:
            raise GithubException(500, None, None, "update failed")

    refreshed: list[str] = []

    def _resolve_token(repository: str) -> str:
        refreshed.append(repository)
        return f"fake-token-{len(refreshed) + 1}"

    monkeypatch.setattr("backend.github.statuses.github_checks.update_check_run", _fake_update_check_run)

    def _record_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("backend.github.statuses.time.sleep", _record_sleep)

    run_id, token_used, ok = statuses._finalize_check_run_with_retry(
        token=initial_token,
        repository="owner/repo",
        sha="a" * 40,
        status_context="BMT Gate",
        check_run_id=17,
        conclusion="failure",
        output={"title": "Gate FAIL", "summary": "failed"},
        details_url="https://example.test/workflows/123",
        token_resolver=_resolve_token,
    )

    assert ok is True
    assert run_id == 17
    assert token_used == "fake-token-3"
    assert sleeps == [1.0, 3.0]
    assert attempts == [
        ("fake-token-1", "https://example.test/workflows/123"),
        ("fake-token-2", "https://example.test/workflows/123"),
        ("fake-token-3", "https://example.test/workflows/123"),
    ]


def test_github_reporter_terminal_methods_delegate_to_retry_helpers(monkeypatch) -> None:
    recorded: dict[str, object] = {}
    initial_token = "fake-token-1"

    def _fake_finalize_helper(**kwargs):
        recorded["finalize_kwargs"] = kwargs
        return 44, "fresh-token", True

    def _fake_status_helper(
        repository: str,
        sha: str,
        state: str,
        description: str,
        target_url: str | None,
        token: str,
        *,
        context: str,
        token_resolver,
        attempts: int = 3,
        _post_func=None,
    ) -> bool:
        recorded["status_call"] = {
            "repository": repository,
            "sha": sha,
            "state": state,
            "description": description,
            "target_url": target_url,
            "token": token,
            "context": context,
            "attempts": attempts,
            "token_resolver": token_resolver,
            "post_func": _post_func,
        }
        return True

    monkeypatch.setattr("backend.github.reporting._finalize_check_run_with_retry", _fake_finalize_helper)
    monkeypatch.setattr("backend.github.reporting._post_commit_status_with_retry", _fake_status_helper)

    reporter = GitHubReporter(repository="owner/repo", sha="a" * 40, token=initial_token, status_context="BMT Gate")
    check_run_id, ok = reporter.finalize_check_run(
        check_run_id=17,
        view=CheckFinalView(
            state="failure",
            links=LiveLinks(workflow_execution_url="https://example.test/workflows/123"),
            bmts=[],
        ),
        details_url="https://example.test/workflows/123",
    )
    status_ok = reporter.post_final_status(
        state="failure",
        description="1/1 BMTs failed.",
        details_url="https://example.test/workflows/123",
    )

    assert (check_run_id, ok) == (44, True)
    assert status_ok is True
    finalize_kwargs = recorded["finalize_kwargs"]
    assert isinstance(finalize_kwargs, dict)
    assert finalize_kwargs["repository"] == "owner/repo"
    assert finalize_kwargs["details_url"] == "https://example.test/workflows/123"
    status_call = recorded["status_call"]
    assert isinstance(status_call, dict)
    assert status_call["repository"] == "owner/repo"
    assert status_call["target_url"] == "https://example.test/workflows/123"
    assert status_call["attempts"] == 3

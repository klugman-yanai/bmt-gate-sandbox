"""Commit status and Check Run helpers for the Cloud Run BMT runtime."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from github import Auth, Github, GithubException

from backend.config.constants import HTTP_TIMEOUT, STATUS_CONTEXT
from backend.config.status import CheckConclusion, CheckStatus
from backend.github import github_checks
from backend.github.presentation import github_check_final_title, render_results_table

DEFAULT_STATUS_CONTEXT: str = STATUS_CONTEXT
_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 3.0)


def _sleep_before_retry(*, attempt: int, max_attempts: int) -> None:
    if attempt >= max_attempts:
        return
    delay = _RETRY_BACKOFF_SECONDS[min(attempt - 1, len(_RETRY_BACKOFF_SECONDS) - 1)]
    time.sleep(delay)


def post_commit_status_request(
    repository: str,
    sha: str,
    state: str,
    description: str,
    target_url: str | None,
    token: str,
    context: str = DEFAULT_STATUS_CONTEXT,
) -> bool:
    """Post a commit status to GitHub. state: pending|success|failure|error."""
    if not token or not repository or not sha:
        return False
    _owner, _slash, repo = repository.partition("/")
    if not repo:
        return False
    ctx = (context or DEFAULT_STATUS_CONTEXT).strip() or DEFAULT_STATUS_CONTEXT
    desc = description[:140]
    try:
        gh = Github(auth=Auth.Token(token), timeout=int(HTTP_TIMEOUT))
        r = gh.get_repo(repository)
        kwargs: dict[str, str] = {
            "state": state,
            "context": ctx,
            "description": desc,
        }
        if target_url:
            kwargs["target_url"] = target_url
        r.get_commit(sha).create_status(**kwargs)
        return True
    except Exception:
        return False


def _with_refreshed_token(
    repository: str,
    token_resolver: Callable[[str], str | None],
    current_token: str,
) -> str:
    """Try resolving a fresh token; fall back to current token on failure."""
    refreshed = token_resolver(repository)
    if refreshed:
        return refreshed
    return current_token


def _post_commit_status_with_retry(
    repository: str,
    sha: str,
    state: str,
    description: str,
    target_url: str | None,
    token: str,
    *,
    context: str,
    token_resolver: Callable[[str], str | None],
    attempts: int = 3,
    _post_func: Callable[..., bool] | None = None,
) -> bool:
    """Post commit status with token refresh retries for transient auth/API issues.

    Optional _post_func allows injection for tests.
    """
    post_fn = _post_func if _post_func is not None else post_commit_status_request
    token_in_use = token
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        if post_fn(repository, sha, state, description, target_url, token_in_use, context=context):
            return True
        if attempt < max_attempts:
            token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
            _sleep_before_retry(attempt=attempt, max_attempts=max_attempts)
    return False


def _create_check_run_resilient(
    token: str,
    repository: str,
    sha: str,
    *,
    name: str,
    status: str,
    output: dict[str, Any],
    details_url: str | None,
    token_resolver: Callable[[str], str | None],
    attempts: int = 3,
) -> tuple[int | None, str]:
    """Create check run with token refresh retries. Returns (check_run_id, token_used)."""
    token_in_use = token
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            check_run_id = github_checks.create_check_run(
                token_in_use,
                repository,
                sha,
                name=name,
                status=status,
                output=output,
                details_url=details_url,
            )
            return check_run_id, token_in_use
        except (OSError, ValueError, RuntimeError, GithubException):
            if attempt < max_attempts:
                token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
                _sleep_before_retry(attempt=attempt, max_attempts=max_attempts)
    return None, token_in_use


def _update_check_run_resilient(
    token: str,
    repository: str,
    check_run_id: int,
    *,
    token_resolver: Callable[[str], str | None],
    status: str | None = None,
    conclusion: str | None = None,
    output: dict[str, Any] | None = None,
    details_url: str | None = None,
    attempts: int = 3,
) -> tuple[bool, str]:
    """Update check run with token refresh retries. Returns (updated, token_used)."""
    token_in_use = token
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            github_checks.update_check_run(
                token_in_use,
                repository,
                check_run_id,
                status=status,
                conclusion=conclusion,
                output=output,
                details_url=details_url,
            )
            return True, token_in_use
        except (OSError, ValueError, RuntimeError, GithubException):
            if attempt < max_attempts:
                token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
                _sleep_before_retry(attempt=attempt, max_attempts=max_attempts)
    return False, token_in_use


def _finalize_check_run_with_retry(
    *,
    token: str,
    repository: str,
    sha: str,
    status_context: str,
    check_run_id: int | None,
    conclusion: str,
    output: dict[str, Any],
    details_url: str | None,
    token_resolver: Callable[[str], str | None],
) -> tuple[int | None, str, bool]:
    """Finalize check run, creating one at completion if initial creation failed."""
    token_in_use = token
    run_id = check_run_id

    if run_id is not None:
        updated, token_in_use = _update_check_run_resilient(
            token_in_use,
            repository,
            run_id,
            token_resolver=token_resolver,
            status=CheckStatus.COMPLETED.value,
            conclusion=conclusion,
            output=output,
            details_url=details_url,
        )
        return run_id, token_in_use, updated

    created_id, token_in_use = _create_check_run_resilient(
        token_in_use,
        repository,
        sha,
        name=status_context,
        status=CheckStatus.IN_PROGRESS.value,
        output={
            "title": "Finalizing",
            "summary": "Posting the final gate result to this check…",
        },
        details_url=details_url,
        token_resolver=token_resolver,
    )
    if created_id is None:
        return None, token_in_use, False

    updated, token_in_use = _update_check_run_resilient(
        token_in_use,
        repository,
        created_id,
        token_resolver=token_resolver,
        status=CheckStatus.COMPLETED.value,
        conclusion=conclusion,
        output=output,
        details_url=details_url,
    )
    return created_id, token_in_use, updated


def finalize_check_run(
    *,
    state: str,
    leg_summaries: list[dict[str, Any] | None],
    run_id: str,
    runtime_bucket_root: str,
    log_dump_url: str | None,
    github_token: str,
    repository: str,
    sha: str,
    runtime_status_context: str,
    check_run_id: int | None,
    details_url: str | None = None,
    token_resolver: Callable[[str], str | None],
) -> tuple[int | None, str, bool]:
    conclusion = (
        CheckConclusion.SUCCESS.value if state == CheckConclusion.SUCCESS.value else CheckConclusion.FAILURE.value
    )
    is_pass = state == CheckConclusion.SUCCESS.value
    return _finalize_check_run_with_retry(
        token=github_token,
        repository=repository,
        sha=sha,
        status_context=runtime_status_context,
        check_run_id=check_run_id,
        conclusion=conclusion,
        output={
            "title": github_check_final_title(is_success=is_pass),
            "summary": render_results_table(
                [summary for summary in leg_summaries if summary is not None],
                {
                    "state": "PASS" if state == CheckConclusion.SUCCESS.value else "FAIL",
                    "decision": state,
                    "reasons": [],
                },
                run_id=run_id,
                runtime_bucket_root=runtime_bucket_root,
                log_dump_url=log_dump_url,
            ),
        },
        details_url=details_url,
        token_resolver=token_resolver,
    )


def post_commit_status(
    *,
    repository: str,
    sha: str,
    state: str,
    description: str,
    github_token: str,
    gate_status_context: str,
    token_resolver: Callable[[str], str | None],
) -> bool:
    return _post_commit_status_with_retry(
        repository,
        sha,
        state,
        description,
        None,
        github_token,
        context=gate_status_context,
        token_resolver=token_resolver,
        attempts=3,
        _post_func=post_commit_status_request,
    )

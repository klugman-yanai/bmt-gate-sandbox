"""Commit status and Check Run resilient wrappers for vm_watcher. Depends on github_checks and config."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from gcp.image.config.constants import GITHUB_API_VERSION, HTTP_TIMEOUT
from gcp.image.github import github_checks

try:
    from config.bmt_config import BmtConfig
except ImportError:
    from gcp.image.config.bmt_config import BmtConfig

DEFAULT_STATUS_CONTEXT: str = BmtConfig().bmt_status_context


def _post_commit_status(
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
    owner, _, repo = repository.partition("/")
    if not repo:
        return False
    url = f"https://api.github.com/repos/{owner}/{repo}/statuses/{sha}"
    body = {
        "state": state,
        "context": (context or DEFAULT_STATUS_CONTEXT).strip() or DEFAULT_STATUS_CONTEXT,
        "description": description[:140],
    }
    if target_url:
        body["target_url"] = target_url
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
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


def _post_commit_status_resilient(
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

    Optional _post_func allows injection for tests (e.g. from vm_watcher).
    """
    post_fn = _post_func if _post_func is not None else _post_commit_status
    token_in_use = token
    max_attempts = max(1, attempts)
    for attempt in range(1, max_attempts + 1):
        if post_fn(repository, sha, state, description, target_url, token_in_use, context=context):
            return True
        if attempt < max_attempts:
            token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
    return False


def _create_check_run_resilient(
    token: str,
    repository: str,
    sha: str,
    *,
    name: str,
    status: str,
    output: dict[str, Any],
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
            )
            return check_run_id, token_in_use
        except (OSError, ValueError, RuntimeError):
            if attempt < max_attempts:
                token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
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
            )
            return True, token_in_use
        except (OSError, ValueError, RuntimeError):
            if attempt < max_attempts:
                token_in_use = _with_refreshed_token(repository, token_resolver, token_in_use)
    return False, token_in_use


def _finalize_check_run_resilient(
    *,
    token: str,
    repository: str,
    sha: str,
    status_context: str,
    check_run_id: int | None,
    conclusion: str,
    output: dict[str, Any],
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
            status="completed",
            conclusion=conclusion,
            output=output,
        )
        return run_id, token_in_use, updated

    created_id, token_in_use = _create_check_run_resilient(
        token_in_use,
        repository,
        sha,
        name=status_context,
        status="in_progress",
        output={
            "title": "BMT Finalizing",
            "summary": "Publishing final results…",
        },
        token_resolver=token_resolver,
    )
    if created_id is None:
        return None, token_in_use, False

    updated, token_in_use = _update_check_run_resilient(
        token_in_use,
        repository,
        created_id,
        token_resolver=token_resolver,
        status="completed",
        conclusion=conclusion,
        output=output,
    )
    return created_id, token_in_use, updated

"""GitHub API helpers using githubkit. Token from env (GITHUB_TOKEN); never log token."""

from __future__ import annotations

import os

from bmtcontract.constants import GITHUB_API_VERSION
from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import GitHubException


class GitHubApiError(RuntimeError):
    """Raised when a GitHub API call fails in a non-recoverable way."""


_GITHUB_CLIENT_ERRORS: tuple[type[BaseException], ...] = (
    GitHubException,
    OSError,
    TypeError,
    ValueError,
)


def _get_token() -> str:
    """Return GITHUB_TOKEN from env. Raises GitHubApiError if unset or empty."""
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        raise GitHubApiError("GITHUB_TOKEN is not set or empty")
    return token


def _split_repository(repository: str) -> tuple[str, str]:
    owner, sep, repo = repository.partition("/")
    if not owner or not sep or not repo:
        raise GitHubApiError(f"Repository must be owner/name, got {repository!r}")
    return owner, repo


def _get_github() -> GitHub:
    return GitHub(auth=TokenAuthStrategy(_get_token()))


def post_commit_status(
    repository: str,
    sha: str,
    state: str,
    context: str,
    description: str,
    *,
    target_url: str | None = None,
) -> None:
    """Post a commit status. state: pending, success, failure, error."""
    gh = _get_github()
    desc = (description or "")[:140]
    try:
        owner, repo_name = _split_repository(repository)
        data: dict[str, str] = {
            "state": state,
            "context": context,
            "description": desc,
        }
        if target_url is not None:
            data["target_url"] = target_url
        gh.rest(GITHUB_API_VERSION).repos.create_commit_status(owner, repo_name, sha, data=data)
    except _GITHUB_CLIENT_ERRORS as exc:
        raise GitHubApiError(f"Failed to post status for {repository}@{sha}: {exc}") from exc


def get_commit_statuses(repository: str, sha: str) -> list[dict[str, str]]:
    """Return list of status dicts (context, state, description, target_url, ...) for the commit."""
    gh = _get_github()
    try:
        owner, repo_name = _split_repository(repository)
        payload = gh.rest(GITHUB_API_VERSION).repos.get_combined_status_for_ref(owner, repo_name, sha).json()
        statuses = payload.get("statuses") if isinstance(payload, dict) else None
        out: list[dict[str, str]] = []
        if not isinstance(statuses, list):
            return out
        for s in statuses:
            if not isinstance(s, dict):
                continue
            out.append(
                {
                    "context": str(s.get("context") or ""),
                    "state": str(s.get("state") or ""),
                    "description": str(s.get("description") or ""),
                    "target_url": str(s.get("target_url") or ""),
                }
            )
        return out
    except _GITHUB_CLIENT_ERRORS as exc:
        raise GitHubApiError(f"Failed to get statuses for {repository}@{sha}: {exc}") from exc


def get_latest_status_state(repository: str, sha: str, context: str) -> str:
    """Return the latest state string for the given context (e.g. 'pending', 'success', 'failure', 'error'), or ''."""
    statuses = get_commit_statuses(repository, sha)
    for s in statuses:
        if s.get("context") == context:
            return s.get("state") or ""
    return ""


def should_post_failure_status(repository: str, sha: str, context: str) -> bool:
    """Return True if we should post a failure status (no terminal status yet). If we cannot read status, return True (fail-safe)."""
    try:
        state = get_latest_status_state(repository, sha, context)
    except GitHubApiError:
        return True  # fail-safe: post failure
    if state in ("", "pending"):
        return True
    return state not in ("success", "failure", "error")


def post_pr_comment(repository: str, pr_number: int, body: str) -> None:
    """Post a comment on a pull request."""
    gh = _get_github()
    try:
        owner, repo_name = _split_repository(repository)
        gh.rest(GITHUB_API_VERSION).issues.create_comment(owner, repo_name, pr_number, data={"body": body})
    except _GITHUB_CLIENT_ERRORS as exc:
        raise GitHubApiError(
            f"Failed to post PR comment on {repository}#{pr_number}: {exc}"
        ) from exc


def trigger_workflow_dispatch(
    repository: str,
    workflow_id: str,
    ref: str,
    *,
    inputs: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """Trigger a workflow_dispatch run and return run details when GitHub includes them."""
    gh = _get_github()
    try:
        owner, repo_name = _split_repository(repository)
        response = gh.rest(GITHUB_API_VERSION).actions.create_workflow_dispatch(
            owner,
            repo_name,
            workflow_id,
            data={"ref": ref, "inputs": inputs or {}},
        )
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except _GITHUB_CLIENT_ERRORS as exc:
        raise GitHubApiError(
            f"Failed to trigger workflow {workflow_id} on {repository}@{ref}: {exc}"
        ) from exc

"""GitHub API helpers using PyGithub. Token from env (GITHUB_TOKEN); never log token."""

from __future__ import annotations

import os


class GitHubApiError(RuntimeError):
    """Raised when a GitHub API call fails in a non-recoverable way."""


def _get_token() -> str:
    """Return GITHUB_TOKEN from env. Raises GitHubApiError if unset or empty."""
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        raise GitHubApiError("GITHUB_TOKEN is not set or empty")
    return token


def _get_github():
    """Lazy import to avoid requiring PyGithub when not using GitHub API."""
    import github

    return github.Github(_get_token())


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
    repo = gh.get_repo(repository)
    desc = (description or "")[:140]
    try:
        kwargs: dict[str, str] = {
            "state": state,
            "context": context,
            "description": desc,
        }
        if target_url is not None:
            kwargs["target_url"] = target_url
        repo.get_commit(sha).create_status(**kwargs)
    except Exception as exc:
        raise GitHubApiError(f"Failed to post status for {repository}@{sha}: {exc}") from exc


def get_commit_statuses(repository: str, sha: str) -> list[dict[str, str]]:
    """Return list of status dicts (context, state, description, target_url, ...) for the commit."""
    gh = _get_github()
    repo = gh.get_repo(repository)
    try:
        status = repo.get_commit(sha).get_combined_status()
        out: list[dict[str, str]] = []
        for s in status.statuses:
            out.append(
                {
                    "context": s.context or "",
                    "state": s.state or "",
                    "description": s.description or "",
                    "target_url": s.target_url or "",
                }
            )
        return out
    except Exception as exc:
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
    repo = gh.get_repo(repository)
    try:
        issue = repo.get_issue(pr_number)
        issue.create_comment(body)
    except Exception as exc:
        raise GitHubApiError(
            f"Failed to post PR comment on {repository}#{pr_number}: {exc}"
        ) from exc


def trigger_workflow_dispatch(
    repository: str,
    workflow_id: str,
    ref: str,
    *,
    inputs: dict[str, str] | None = None,
) -> None:
    """Trigger a workflow_dispatch run. workflow_id can be workflow filename (e.g. bmt.yml) or numeric id."""
    gh = _get_github()
    repo = gh.get_repo(repository)
    try:
        workflow = repo.get_workflow(workflow_id)
        workflow.create_dispatch(ref, inputs or {})
    except Exception as exc:
        raise GitHubApiError(
            f"Failed to trigger workflow {workflow_id} on {repository}@{ref}: {exc}"
        ) from exc


def find_newer_in_progress_pr_run(
    repository: str,
    *,
    workflow_name: str,
    head_branch: str,
    current_run_id: int,
    pr_number: int | None = None,
) -> int | None:
    """Return newer in-progress run id for same PR/branch/workflow, else None."""
    gh = _get_github()
    repo = gh.get_repo(repository)
    try:
        runs = repo.get_workflow_runs(event="pull_request", branch=head_branch)
    except Exception as exc:
        raise GitHubApiError(
            f"Failed to list pull_request runs for {repository} branch {head_branch}: {exc}"
        ) from exc

    active = {"queued", "in_progress", "waiting", "requested", "pending"}
    newest: int | None = None
    for run in runs:
        try:
            run_name = (run.name or "").strip()
            run_status = (run.status or "").strip().lower()
            run_id = int(run.id)
        except Exception:
            continue

        if run_name != workflow_name:
            continue
        if run_id <= current_run_id:
            continue
        if run_status not in active:
            continue

        if pr_number is not None:
            prs = getattr(run, "pull_requests", None) or []
            pr_numbers = set()
            for pr in prs:
                num = getattr(pr, "number", None)
                if isinstance(num, int):
                    pr_numbers.add(num)
            if pr_numbers and pr_number not in pr_numbers:
                continue

        if newest is None or run_id > newest:
            newest = run_id

    return newest

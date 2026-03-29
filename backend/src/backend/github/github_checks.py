"""GitHub Check Runs API integration for BMT Gate (Checks tab).

Output format per docs/architecture.md (GitHub and CI): pass/fail, scores, logs. The Check Run
appears on the PR Checks tab; branch protection can require it to pass before merge.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from backend.github.client import github_client, github_rest, split_repository

# GitHub REST API documents large max for check run output fields; stay under a safe UTF-8 byte cap.
GITHUB_CHECK_OUTPUT_FIELD_MAX_BYTES = 65535


def clamp_utf8_by_bytes(text: str, max_bytes: int = GITHUB_CHECK_OUTPUT_FIELD_MAX_BYTES) -> str:
    """Truncate ``text`` so its UTF-8 encoding does not exceed ``max_bytes`` (valid Unicode suffix)."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    truncated = raw[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


class CheckRunOutput(TypedDict):
    """GitHub Checks API ``output`` object (``text`` and ``annotations`` optional)."""

    title: str
    summary: str
    text: NotRequired[str]
    annotations: NotRequired[list[dict[str, Any]]]


def _normalize_check_output(output: CheckRunOutput | dict[str, Any]) -> dict[str, Any]:
    """Omit empty optional ``text`` / ``annotations``; GitHub accepts title + summary only."""
    out = {k: v for k, v in output.items() if v is not None}
    sum_v = out.get("summary")
    if isinstance(sum_v, str):
        out["summary"] = clamp_utf8_by_bytes(sum_v)
    text_v = out.get("text")
    if isinstance(text_v, str):
        out["text"] = clamp_utf8_by_bytes(text_v)
    if out.get("text") == "":
        out.pop("text", None)
    if not out.get("annotations"):
        out.pop("annotations", None)
    return out


def _github_repo(token: str, repo: str) -> Any:
    client = github_client(token)
    owner, repo_name = split_repository(repo)
    return client, owner, repo_name


def create_check_run(
    token: str,
    repo: str,
    sha: str,
    name: str,
    status: str,
    output: CheckRunOutput | dict[str, Any],
    *,
    details_url: str | None = None,
    external_id: str | None = None,
) -> int:
    """Create a GitHub Check Run.

    Args:
        token: GitHub token with checks:write permission
        repo: Repository in format "owner/name"
        sha: Commit SHA
        name: Check run name (e.g., "BMT Gate")
        status: Check run status ("queued", "in_progress", "completed")
        output: Output dict with ``title``, ``summary``, and optional ``text`` (Markdown)

    Returns:
        Check run ID for future updates

    Raises:
        githubkit.exception.GitHubException: If the GitHub API request fails
        TypeError: If the check run id is missing
    """
    client, owner, repo_name = _github_repo(token, repo)
    normalized = _normalize_check_output(output)
    data: dict[str, Any] = {
        "name": name,
        "head_sha": sha,
        "status": status,
        "output": normalized,
    }
    if details_url is not None:
        data["details_url"] = details_url
    if external_id is not None:
        data["external_id"] = external_id
    payload = github_rest(client).checks.create(owner, repo_name, data=data).json()
    rid = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(rid, int):
        raise TypeError("GitHub check run create response missing integer id")
    return rid


def update_check_run(
    token: str,
    repo: str,
    check_run_id: int,
    status: str | None = None,
    conclusion: str | None = None,
    output: CheckRunOutput | dict[str, Any] | None = None,
    details_url: str | None = None,
) -> None:
    """Update an existing Check Run.

    Args:
        token: GitHub token with checks:write permission
        repo: Repository in format "owner/name"
        check_run_id: ID returned from create_check_run
        status: New status ("in_progress", "completed"), or None to keep current
        conclusion: Conclusion when status="completed" ("success", "failure", etc.)
        output: New output dict with ``title``, ``summary``, optional ``text``, or None to keep current

    Raises:
        githubkit.exception.GitHubException: If the GitHub API request fails
    """
    client, owner, repo_name = _github_repo(token, repo)
    data: dict[str, Any] = {}
    if status is not None:
        data["status"] = status
    if conclusion is not None:
        data["conclusion"] = conclusion
    if output is not None:
        data["output"] = _normalize_check_output(output)
    if details_url is not None:
        data["details_url"] = details_url
    github_rest(client).checks.update(owner, repo_name, check_run_id, data=data)


def get_check_run_status(token: str, repo: str, check_run_id: int) -> str:
    """Return GitHub check run ``status`` (e.g. ``queued``, ``in_progress``, ``completed``)."""
    client, owner, repo_name = _github_repo(token, repo)
    payload = github_rest(client).checks.get(owner, repo_name, check_run_id).json()
    raw = payload.get("status") if isinstance(payload, dict) else None
    return raw if isinstance(raw, str) else str(raw)

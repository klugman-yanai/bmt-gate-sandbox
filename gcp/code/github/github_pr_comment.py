"""Post comments on a GitHub PR (Issues API).

Used by the BMT VM to post the \"Later\" PR comment: pass/fail, scores, logs
(see docs/github-and-ci.md). The workflow posts the \"Now\" comment; the VM
upserts a second comment when the run completes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from gcp.code.config.constants import GITHUB_API_VERSION, HTTP_TIMEOUT


def _split_repo(repo: str) -> tuple[str, str] | None:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        return None
    return owner, name


def _request_json(
    token: str,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = HTTP_TIMEOUT,
) -> tuple[bool, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8") or "null"
            return 200 <= resp.status < 300, json.loads(text)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError):
        return False, None


def post_pr_comment(token: str, repo: str, issue_number: int, body: str) -> bool:
    """Post a comment on a PR (issue).

    Args:
        token: GitHub token with Issues or Pull requests write permission.
        repo: Repository in format "owner/name".
        issue_number: PR number (PRs are issues).
        body: Comment body (markdown).

    Returns:
        True if the API returned 2xx, False otherwise. Logs and swallows errors.
    """
    if not token or not repo or not body:
        return False
    repo_parts = _split_repo(repo)
    if repo_parts is None:
        return False
    owner, name = repo_parts
    url = f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments"
    ok, _ = _request_json(token, url, method="POST", payload={"body": body}, timeout=HTTP_TIMEOUT)
    if not ok:
        pass
    return ok


def list_pr_comments(token: str, repo: str, issue_number: int, *, per_page: int = 100) -> list[dict[str, Any]]:
    """List PR comments using the Issues API, newest first across pages."""
    comments: list[dict[str, Any]] = []
    repo_parts = _split_repo(repo) if token and repo and issue_number > 0 else None
    if repo_parts is not None:
        owner, name = repo_parts
        page = 1
        page_size = max(1, min(int(per_page or 100), 100))
        done = False
        while page <= 10 and not done:
            url = (
                f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments"
                f"?per_page={page_size}&page={page}"
            )
            ok, payload = _request_json(token, url, method="GET", payload=None, timeout=HTTP_TIMEOUT)
            if not ok or not isinstance(payload, list):
                done = True
                continue
            page_comments = [item for item in payload if isinstance(item, dict)]
            if not page_comments:
                done = True
                continue
            comments.extend(page_comments)
            if len(page_comments) < page_size:
                done = True
                continue
            page += 1
    return comments


def update_pr_comment(token: str, repo: str, comment_id: int, body: str) -> bool:
    """Update an existing PR comment by comment id."""
    if not token or not repo or comment_id <= 0 or not body:
        return False
    repo_parts = _split_repo(repo)
    if repo_parts is None:
        return False
    owner, name = repo_parts
    url = f"https://api.github.com/repos/{owner}/{name}/issues/comments/{comment_id}"
    ok, _ = _request_json(token, url, method="PATCH", payload={"body": body}, timeout=HTTP_TIMEOUT)
    if not ok:
        pass
    return ok


def upsert_pr_comment_by_marker(token: str, repo: str, issue_number: int, marker: str, body: str) -> bool:
    """Create or update one VM-owned PR comment identified by a stable marker."""
    if not token or not repo or issue_number <= 0 or not marker or not body:
        return False
    for comment in list_pr_comments(token, repo, issue_number):
        comment_body = comment.get("body")
        if not isinstance(comment_body, str) or marker not in comment_body:
            continue
        raw_id = comment.get("id")
        with_id = int(raw_id) if isinstance(raw_id, int) else None
        if with_id is not None:
            return update_pr_comment(token, repo, with_id, body)
    return post_pr_comment(token, repo, issue_number, body)

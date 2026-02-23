"""Post a comment on a GitHub PR (issue) using the Issues API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


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
    owner, _, name = repo.partition("/")
    if not name:
        return False
    url = f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments"
    data = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        print(f"  Failed to post PR comment: {exc}")
        return False

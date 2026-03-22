"""Shared gh CLI helpers for tools that need repo vars, branch rules, or command checks."""

from __future__ import annotations

import json
import subprocess


def cmd_exists(name: str) -> bool:
    """Return True if the given command is on PATH."""
    return subprocess.run(["which", name], capture_output=True, check=False).returncode == 0


def gh_var(name: str) -> str | None:
    """Return the value of a GitHub repo variable, or None if unset or gh unavailable."""
    if not cmd_exists("gh"):
        return None
    result = subprocess.run(
        ["gh", "variable", "get", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def gh_repo_slug() -> str | None:
    """Return owner/repo for the current repo, or None if gh unavailable."""
    if not cmd_exists("gh"):
        return None
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    slug = result.stdout.strip()
    return slug if result.returncode == 0 and "/" in slug else None


def required_status_contexts_for_branch(repo_slug: str, branch: str) -> list[str] | None:
    """Return required status check contexts for the branch, or None on API error."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo_slug}/rules/branches/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        checks = data.get("required_status_checks")
        if not checks or not isinstance(checks.get("contexts"), list):
            return []
        return [str(c) for c in checks["contexts"]]
    except (json.JSONDecodeError, TypeError):
        return None

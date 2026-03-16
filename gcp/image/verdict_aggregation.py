"""Verdict aggregation and comment text for vm_watcher. No GCP/github deps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_manager_summary(run_root: Path | None) -> dict[str, Any] | None:
    """Load manager_summary.json from a run root; return None if missing or invalid."""
    if run_root is None:
        return None
    path = run_root / "manager_summary.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _aggregate_verdicts_from_summaries(summaries: list[dict[str, Any] | None]) -> tuple[str, str]:
    """Compute (state, description) from manager summaries. state: success|failure."""
    pass_count = 0
    fail_count = 0
    for summary in summaries:
        if summary is None:
            fail_count += 1
            continue
        status = (summary.get("status") or "").strip().lower()
        if status in ("pass", "warning"):
            pass_count += 1
        else:
            fail_count += 1
    total = len(summaries)
    if fail_count == 0:
        return "success", f"{pass_count}/{total} test suites passed"
    return "failure", f"{fail_count}/{total} test suites failed, {pass_count} passed"


def _short_sha(sha: str, *, length: int = 12) -> str:
    """Return short SHA for display while preserving the full hash elsewhere."""
    clean = (sha or "").strip()
    if not clean:
        return "unknown"
    return clean[: max(4, length)]


def _commit_url(repository: str, sha: str, server_url: str = "https://github.com") -> str:
    """Build commit URL when repository and SHA are available."""
    repo = (repository or "").strip()
    clean_sha = (sha or "").strip()
    base = (server_url or "https://github.com").rstrip("/")
    if not repo or not clean_sha:
        return ""
    return f"{base}/{repo}/commit/{clean_sha}"


def _commit_markdown_link(repository: str, sha: str, server_url: str = "https://github.com") -> str:
    """Render commit link markdown with short SHA text."""
    url = _commit_url(repository, sha, server_url)
    short = _short_sha(sha)
    if not url:
        return f"`{short}`"
    return f"[`{short}`]({url})"


def _comment_marker_for_sha(sha: str) -> str:
    """Stable hidden marker used for commit-specific PR comment upsert."""
    return f"<!-- bmt-vm-comment-sha:{(sha or '').strip()} -->"


def _format_bmt_comment(
    result: str,
    summary_line: str,
    details_line: str,
    *,
    repository: str,
    tested_sha: str,
    workflow_run_id: str | int | None,
    pr_number: int | None = None,
    server_url: str = "https://github.com",
    superseding_sha: str | None = None,
) -> str:
    """Build PR comment body with commit linkage and stable marker for upsert.
    Always includes direct links: commit, workflow run, and Checks tab.
    """
    base = (server_url or "https://github.com").rstrip("/")
    commit_link = _commit_markdown_link(repository, tested_sha, server_url)
    workflow_link = ""
    if workflow_run_id is not None:
        run_id_str = str(workflow_run_id).strip()
        if run_id_str:
            workflow_link = f"[Workflow run]({base}/{repository}/actions/runs/{run_id_str})"
    checks_link = f"[Checks tab]({base}/{repository}/commit/{tested_sha}/checks)"
    if pr_number is not None and pr_number > 0:
        checks_link = f"[Checks tab]({base}/{repository}/pull/{pr_number}/checks)"

    link_parts = [commit_link]
    if workflow_link:
        link_parts.append(workflow_link)
    link_parts.append(checks_link)
    links_line = " · ".join(link_parts)

    lines = [
        _comment_marker_for_sha(tested_sha),
        f"## {result}",
        "",
        links_line,
        "",
        summary_line,
    ]
    if details_line:
        lines.extend(["", details_line])
    if superseding_sha:
        lines.extend(["", f"Superseded by {_commit_markdown_link(repository, superseding_sha, server_url)}"])
    return "\n".join(lines)


def _human_readable_bmt_label(bmt_id: str) -> str:
    """Turn bmt_id (e.g. false_reject_namuh) into display text (e.g. False Rejects)."""
    if not bmt_id or bmt_id == "?":
        return bmt_id or "?"
    return bmt_id.replace("_", " ").strip().title()


def _failed_legs_display(summaries: list[dict[str, Any] | None]) -> str:
    """List failed project · BMT in human-readable form for PR comment."""
    parts: list[str] = []
    for summary in summaries or []:
        if summary is None:
            continue
        status = (summary.get("status") or "").strip().lower()
        if status in ("pass", "warning"):
            continue
        project = (summary.get("project_id") or summary.get("project") or "?").strip()
        if project and project != "?":
            project = project.upper() if len(project) <= 3 else project.title()
        bmt_id = (summary.get("bmt_id") or "?").strip()
        bmt_label = _human_readable_bmt_label(bmt_id) if bmt_id != "?" else "?"
        parts.append(f"**{project} · {bmt_label}**")
    if not parts:
        return "One or more test suites did not pass."
    return "Failed: " + "; ".join(parts)

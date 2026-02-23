"""GitHub Check Runs API integration for live BMT progress updates.

This module provides functions to create and update GitHub Check Runs,
which appear in the PR UI with live progress information.
"""

from typing import Any

import requests


def create_check_run(
    token: str,
    repo: str,
    sha: str,
    name: str,
    status: str,
    output: dict[str, str]
) -> int:
    """Create a GitHub Check Run.

    Args:
        token: GitHub token with checks:write permission
        repo: Repository in format "owner/name"
        sha: Commit SHA
        name: Check run name (e.g., "BMT Gate")
        status: Check run status ("queued", "in_progress", "completed")
        output: Output dict with "title" and "summary" keys

    Returns:
        Check run ID for future updates

    Raises:
        requests.HTTPError: If GitHub API request fails
    """
    url = f"https://api.github.com/repos/{repo}/check-runs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    payload = {
        "name": name,
        "head_sha": sha,
        "status": status,
        "output": output
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()["id"]


def update_check_run(
    token: str,
    repo: str,
    check_run_id: int,
    status: str | None = None,
    conclusion: str | None = None,
    output: dict[str, str] | None = None
) -> None:
    """Update an existing Check Run.

    Args:
        token: GitHub token with checks:write permission
        repo: Repository in format "owner/name"
        check_run_id: ID returned from create_check_run
        status: New status ("in_progress", "completed"), or None to keep current
        conclusion: Conclusion when status="completed" ("success", "failure", etc.)
        output: New output dict with "title" and "summary", or None to keep current

    Raises:
        requests.HTTPError: If GitHub API request fails
    """
    url = f"https://api.github.com/repos/{repo}/check-runs/{check_run_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    payload: dict[str, Any] = {}
    if status is not None:
        payload["status"] = status
    if conclusion is not None:
        payload["conclusion"] = conclusion
    if output is not None:
        payload["output"] = output

    response = requests.patch(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()


def render_progress_markdown(
    legs: list[dict[str, Any]],
    elapsed_sec: int,
    eta_sec: int | None
) -> str:
    """Render progress table as markdown for Check Run output.

    Args:
        legs: List of leg status dicts
        elapsed_sec: Seconds elapsed since execution started
        eta_sec: Estimated seconds remaining, or None if unknown

    Returns:
        Markdown string with progress table
    """
    lines = []

    # Header
    legs_completed = sum(1 for leg in legs if leg["status"] not in ["pending", "running"])
    legs_total = len(legs)
    lines.append("## BMT Execution Progress")
    lines.append("")
    lines.append(f"**Status:** Running ({legs_completed}/{legs_total} legs complete)")
    lines.append(f"**Elapsed:** {_format_duration(elapsed_sec)}")

    if eta_sec is not None:
        lines.append(f"**ETA:** ~{_format_duration(eta_sec)} remaining")
    else:
        lines.append("**ETA:** Unknown (first run)")

    lines.append("")

    # Legs table
    lines.append("### Legs")
    lines.append("")
    lines.append("| Project | BMT | Status | Progress | Duration |")
    lines.append("|---------|-----|--------|----------|----------|")

    for leg in legs:
        project = leg["project"]
        bmt_id = leg["bmt_id"]

        # Status icon and text
        status = leg["status"]
        if status == "pass":
            status_display = "✅ pass"
        elif status == "fail":
            status_display = "❌ fail"
        elif status == "running":
            status_display = "🔵 running"
        else:  # pending
            status_display = "⚪ pending"

        # Progress
        files_completed = leg.get("files_completed", 0)
        files_total = leg.get("files_total")
        if files_total is not None:
            progress = f"{files_completed}/{files_total} files"
        else:
            progress = "—"

        # Duration
        duration_sec = leg.get("duration_sec")
        if duration_sec is not None:
            duration = _format_duration(duration_sec)
        else:
            duration = "—"

        lines.append(f"| {project} | {bmt_id} | {status_display} | {progress} | {duration} |")

    lines.append("")
    lines.append("---")
    lines.append("🤖 Live updates via BMT Monitor")

    return "\n".join(lines)


def render_results_table(
    leg_summaries: list[dict[str, Any]],
    aggregate: dict[str, Any]
) -> str:
    """Render final results table as markdown.

    Args:
        leg_summaries: List of manager summary dicts
        aggregate: Aggregate verdict dict with state/decision/reasons

    Returns:
        Markdown string with results table
    """
    lines = []

    # Overall result
    state = aggregate["state"]
    if state == "PASS":
        lines.append("## ✅ BMT Complete: PASS")
    else:
        lines.append("## ❌ BMT Complete: FAIL")

    lines.append("")
    lines.append(f"**Decision:** {aggregate['decision']}")

    if aggregate.get("reasons"):
        lines.append(f"**Reasons:** {', '.join(aggregate['reasons'])}")

    lines.append("")

    # Per-leg results
    lines.append("### Results by Leg")
    lines.append("")
    lines.append("| Project | BMT | Verdict | Score | Duration |")
    lines.append("|---------|-----|---------|-------|----------|")

    for summary in leg_summaries:
        project = summary.get("project_id", "unknown")
        bmt_id = summary.get("bmt_id", "unknown")

        ci_verdict = summary.get("ci_verdict", {})
        verdict = ci_verdict.get("verdict", "UNKNOWN")
        if verdict == "PASS":
            verdict_display = "✅ PASS"
        else:
            verdict_display = "❌ FAIL"

        # Get score from results
        bmt_results = summary.get("bmt_results", {})
        scores = [r.get("score", 0) for r in bmt_results.get("results", [])]
        avg_score = sum(scores) / len(scores) if scores else 0

        # Duration
        timing = summary.get("orchestration_timing", {})
        duration_sec = timing.get("duration_sec")
        if duration_sec is not None:
            duration = _format_duration(duration_sec)
        else:
            duration = "—"

        lines.append(f"| {project} | {bmt_id} | {verdict_display} | {avg_score:.1f} | {duration} |")

    lines.append("")
    lines.append("---")
    lines.append("🤖 Generated by BMT Monitor")

    return "\n".join(lines)


def _format_duration(seconds: int) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2m 15s", "1h 5m")
    """
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"

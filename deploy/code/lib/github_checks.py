"""GitHub Check Runs API integration for live BMT progress updates.

This module provides functions to create and update GitHub Check Runs,
which appear in the PR UI with live progress information.
"""

from datetime import UTC, datetime
from typing import Any

import requests

_REASON_LABELS: dict[str, str] = {
    "score_below_last": "Score dropped below baseline",
    "score_above_last": "Score exceeded baseline (lte check failed)",
    "score_gte_last": "Score at or above baseline",
    "score_lte_last": "Score at or below baseline",
    "bootstrap_no_previous_result": "First run — no baseline to compare",
    "runner_failures": "One or more runner processes exited non-zero or timed out",
    "runner_timeout": "One or more runner processes timed out",
    "demo_force_pass": "Forced pass override (demo mode)",
    "bootstrap_without_baseline": "Passed without baseline (warning)",
}


def _human_reason(code: str) -> str:
    return _REASON_LABELS.get(code, code)


def _delta_str(delta: float | None, tolerance_abs: float, passed: bool) -> str:
    if delta is None:
        return "—"
    sign = "+" if delta >= 0 else ""
    s = f"{sign}{delta:.2f}"
    if passed and tolerance_abs > 0 and abs(delta) / tolerance_abs >= 0.5:
        pct = abs(delta) / tolerance_abs * 100
        s += f" ({pct:.0f}% of ±{tolerance_abs})"
    return s


def create_check_run(token: str, repo: str, sha: str, name: str, status: str, output: dict[str, Any]) -> int:
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
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {"name": name, "head_sha": sha, "status": status, "output": output}

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()["id"]


def update_check_run(
    token: str,
    repo: str,
    check_run_id: int,
    status: str | None = None,
    conclusion: str | None = None,
    output: dict[str, Any] | None = None,
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
        "X-GitHub-Api-Version": "2022-11-28",
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


def render_progress_markdown(legs: list[dict[str, Any]], elapsed_sec: int, eta_sec: int | None) -> str:
    """Render progress table as markdown for Check Run output (GitHub browser).

    Optimized for what devs see in the PR: headline first, then table.
    """
    legs_completed = sum(1 for leg in legs if leg["status"] not in ["pending", "running"])
    legs_total = len(legs)
    elapsed_str = _format_duration(elapsed_sec)
    eta_str = f"~{_format_duration(eta_sec)} left" if eta_sec is not None else "ETA unknown"

    lines = [
        f"**{legs_completed}/{legs_total} complete** · {elapsed_str} elapsed · {eta_str}",
        "",
        "| Project | BMT | Status | Progress | Duration |",
        "|---------|-----|--------|----------|----------|",
    ]

    for leg in legs:
        project = leg["project"]
        bmt_id = leg["bmt_id"]
        status = leg["status"]
        if status == "pass":
            status_display = "✅ pass"
        elif status == "fail":
            status_display = "❌ fail"
        elif status == "running":
            status_display = "🔵 running"
        else:
            status_display = "⚪ pending"
        files_completed = leg.get("files_completed", 0)
        files_total = leg.get("files_total")
        progress = f"{files_completed}/{files_total}" if files_total is not None else "—"
        duration_sec = leg.get("duration_sec")
        duration = _format_duration(duration_sec) if duration_sec is not None else "—"
        lines.append(f"| {project} | {bmt_id} | {status_display} | {progress} | {duration} |")

    lines.append(f"\n_Updated {datetime.now(UTC).strftime('%H:%M UTC')}_")
    return "\n".join(lines)


def render_results_table(leg_summaries: list[dict[str, Any]], aggregate: dict[str, Any]) -> str:
    """Render final results table as markdown.

    Args:
        leg_summaries: List of manager summary dicts
        aggregate: Aggregate verdict dict with state/decision/reasons

    Returns:
        Markdown string with results table
    """
    lines = []

    lines.append("| Project | BMT | Verdict | Score | Baseline | Delta | Reason | Duration |")
    lines.append("|---------|-----|---------|-------|----------|-------|--------|----------:|")

    for summary in leg_summaries:
        project = summary.get("project_id", "unknown")
        bmt_id = summary.get("bmt_id", "unknown")

        # Manager summary uses "status" ("pass"/"fail") and "passed" (bool).
        passed = summary.get("passed", False)
        status = summary.get("status", "unknown")
        if passed or status == "pass":
            verdict_display = "✅ PASS"
        else:
            verdict_display = "❌ FAIL"

        # Scores from manager summary and gate.
        current_score = float(summary.get("aggregate_score", 0) or 0)
        gate = summary.get("gate", {}) if isinstance(summary.get("gate"), dict) else {}
        last_score = gate.get("last_score")
        if last_score is None:
            last_score = summary.get("last_score")
        if isinstance(last_score, (int, float)):
            baseline_str = f"{float(last_score):.1f}"
        else:
            baseline_str = "—"

        # Delta with grace annotation.
        delta = summary.get("delta_from_previous")
        tolerance_abs = float(gate.get("tolerance_abs") or 0)
        delta_display = _delta_str(delta, tolerance_abs, bool(passed or status == "pass"))

        reason_display = _human_reason(summary.get("reason_code", "") or "")

        # Duration from orchestration_timing.
        timing = summary.get("orchestration_timing", {})
        duration_sec = timing.get("duration_sec")
        duration = _format_duration(duration_sec) if duration_sec is not None else "—"

        lines.append(
            f"| {project} | {bmt_id} | {verdict_display} "
            f"| {current_score:.1f} | {baseline_str} | {delta_display} | {reason_display} | {duration} |"
        )

    # Failure guidance.
    failed_reasons = [
        summary.get("reason_code", "") or ""
        for summary in leg_summaries
        if not (summary.get("passed") or summary.get("status") == "pass")
    ]
    if failed_reasons:
        lines += ["", "**Next steps**", ""]
        if "runner_failures" in failed_reasons or "runner_timeout" in failed_reasons:
            log_links = []
            for summary in leg_summaries:
                if summary.get("reason_code") in ("runner_failures", "runner_timeout"):
                    uri = (summary.get("ci_verdict_uri") or "").strip()
                    if uri.endswith("ci_verdict.json"):
                        logs_uri = uri[: -len("ci_verdict.json")] + "logs/"
                        log_links.append(f"  - `{summary.get('project_id', '?')}.{summary.get('bmt_id', '?')}`: `{logs_uri}`")
            lines.append("- Runner failed — check per-file logs:")
            if log_links:
                lines.extend(log_links)
            else:
                lines.append("  - Logs: `runtime/<results_prefix>/snapshots/<run_id>/logs/`")
        if any(r in ("score_below_last", "score_above_last") for r in failed_reasons):
            lines.append("- Score dropped below baseline — see delta above. Baseline updates on next passing merge.")
        if "bootstrap_no_previous_result" in failed_reasons:
            lines.append("- No baseline yet — will be set once this run passes.")

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

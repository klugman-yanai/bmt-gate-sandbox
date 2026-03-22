"""GitHub Check Runs API integration for BMT Gate (Checks tab).

Output format per docs/architecture.md (GitHub and CI): pass/fail, scores, logs. The Check Run
appears on the PR Checks tab; branch protection can require it to pass before merge.
"""

from typing import Any

import httpx
from whenever import Instant

from gcp.image.config.bmt_domain_status import (
    BmtLegStatus,
    BmtProgressStatus,
    leg_status_is_pass,
    progress_status_is_in_flight,
    summary_dict_leg_passed,
)
from gcp.image.config.constants import HTTP_TIMEOUT
from gcp.image.config.decisions import ReasonCode
from gcp.image.github.github_auth import github_api_headers
from gcp.image.github.presentation import human_reason as _human_reason

_RUNNER_FAILURE_REASONS = frozenset({ReasonCode.RUNNER_FAILURES.value, ReasonCode.RUNNER_TIMEOUT.value})


def gcs_uri_to_console_url(gs_uri: str) -> str:
    """Convert a gs:// URI to a GCS Console browser URL (option 1: no signing).

    Example: gs://my-bucket/runtime/foo/logs -> https://console.cloud.google.com/storage/browser/my-bucket/runtime/foo/logs
    """
    if not gs_uri or not (gs_uri.startswith("gs://")):
        return ""
    rest = gs_uri[5:].strip("/")
    if not rest:
        return ""
    parts = rest.split("/", 1)
    bucket = parts[0]
    path = parts[1] if len(parts) > 1 else ""
    if not bucket:
        return ""
    return f"https://console.cloud.google.com/storage/browser/{bucket}/{path}"


def _delta_str(delta: float | None, tolerance_abs: float, *, passed: bool) -> str:
    if delta is None:
        return "—"
    sign = "+" if delta >= 0 else ""
    s = f"{sign}{delta:.2f}"
    if passed and tolerance_abs > 0 and abs(delta) / tolerance_abs >= 0.5:
        pct = abs(delta) / tolerance_abs * 100
        s += f" ({pct:.0f}% of ±{tolerance_abs})"
    return s


def create_check_run(
    token: str,
    repo: str,
    sha: str,
    name: str,
    status: str,
    output: dict[str, Any],
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
        output: Output dict with "title" and "summary" keys

    Returns:
        Check run ID for future updates

    Raises:
        httpx.HTTPStatusError: If GitHub API request fails
    """
    url = f"https://api.github.com/repos/{repo}/check-runs"
    headers = github_api_headers(token)

    payload: dict[str, Any] = {"name": name, "head_sha": sha, "status": status, "output": output}
    if details_url:
        payload["details_url"] = details_url
    if external_id:
        payload["external_id"] = external_id

    response = httpx.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.json()["id"]


def update_check_run(
    token: str,
    repo: str,
    check_run_id: int,
    status: str | None = None,
    conclusion: str | None = None,
    output: dict[str, Any] | None = None,
    details_url: str | None = None,
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
        httpx.HTTPStatusError: If GitHub API request fails
    """
    url = f"https://api.github.com/repos/{repo}/check-runs/{check_run_id}"
    headers = github_api_headers(token)

    payload: dict[str, Any] = {}
    if status is not None:
        payload["status"] = status
    if conclusion is not None:
        payload["conclusion"] = conclusion
    if output is not None:
        payload["output"] = output
    if details_url is not None:
        payload["details_url"] = details_url

    response = httpx.patch(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
    response.raise_for_status()


def render_progress_markdown(legs: list[dict[str, Any]], elapsed_sec: int, eta_sec: int | None) -> str:
    """Render in-progress table for BMT Gate Check Run (pass/fail per leg, progress).

    See docs/architecture.md (GitHub and CI). Final output uses render_results_table (scores, logs).
    """
    legs_completed = sum(1 for leg in legs if not progress_status_is_in_flight(str(leg.get("status") or "")))
    legs_total = len(legs)
    elapsed_str = _format_duration(elapsed_sec)
    eta_str = f"~{_format_duration(eta_sec)} left" if eta_sec is not None else "ETA unknown"

    lines = [
        f"**{legs_completed}/{legs_total} tasks complete** · {elapsed_str} elapsed · {eta_str}",
        "",
        "| Project | Test suite | Status | Progress | Duration |",
        "|---------|------------|--------|----------|----------|",
    ]

    for leg in legs:
        project = leg["project"]
        bmt_id = leg["bmt_id"]
        status = str(leg.get("status") or "")
        if status == BmtLegStatus.PASS.value:
            status_display = "✅ pass"
        elif status == BmtLegStatus.FAIL.value:
            status_display = "❌ fail"
        elif status == BmtProgressStatus.RUNNING.value:
            status_display = "🔵 running"
        else:
            status_display = "⚪ pending"
        files_completed = leg.get("files_completed", 0)
        files_total = leg.get("files_total")
        progress = f"{files_completed}/{files_total}" if files_total is not None else "—"
        duration_sec = leg.get("duration_sec")
        duration = _format_duration(duration_sec) if duration_sec is not None else "—"
        lines.append(f"| {project} | {bmt_id} | {status_display} | {progress} | {duration} |")

    lines.append(f"\n_Updated {Instant.now().format_iso(unit='second')[11:16]} UTC_")
    return "\n".join(lines)


def _leg_row_line(summary: dict[str, Any]) -> str:
    project = summary.get("project_id", "unknown")
    bmt_id = summary.get("bmt_id", "unknown")
    passed = summary.get("passed", False)
    status = summary.get("status", "unknown")
    verdict_display = "✅ PASS" if (passed or leg_status_is_pass(status)) else "❌ FAIL"
    current_score = float(summary.get("aggregate_score", 0) or 0)
    gate = summary.get("gate", {}) if isinstance(summary.get("gate"), dict) else {}
    last_score = gate.get("last_score") if gate.get("last_score") is not None else summary.get("last_score")
    baseline_str = f"{float(last_score):.1f}" if isinstance(last_score, (int, float)) else "—"
    delta = summary.get("delta_from_previous")
    tolerance_abs = float(gate.get("tolerance_abs") or 0)
    delta_display = _delta_str(delta, tolerance_abs, passed=bool(passed or leg_status_is_pass(status)))
    reason_display = _human_reason(summary.get("reason_code", "") or "")
    timing = summary.get("orchestration_timing", {})
    duration_sec = timing.get("duration_sec")
    duration = _format_duration(duration_sec) if duration_sec is not None else "—"
    return f"| {project} | {bmt_id} | {verdict_display} | {current_score:.1f} | {baseline_str} | {delta_display} | {reason_display} | {duration} |"


def _failure_guidance_lines(leg_summaries: list[dict[str, Any]], failed_reasons: list[str]) -> list[str]:
    out: list[str] = []
    if not failed_reasons:
        return out
    out += ["", "**Next steps**", ""]
    if any(r in _RUNNER_FAILURE_REASONS for r in failed_reasons):
        log_links = []
        for summary in leg_summaries:
            if summary.get("reason_code") in _RUNNER_FAILURE_REASONS:
                uri = (summary.get("ci_verdict_uri") or "").strip()
                if uri.endswith("ci_verdict.json"):
                    logs_uri = uri[: -len("ci_verdict.json")] + "logs/"
                    log_links.append(
                        f"  - `{summary.get('project_id', '?')}.{summary.get('bmt_id', '?')}`: `{logs_uri}`"
                    )
        out.append("- Runner failed — check per-file logs:")
        out.extend(log_links or ["  - Logs are in cloud storage; see links above when available."])
    if any(r in ("score_below_last", "score_above_last") for r in failed_reasons):
        out.append("- Score dropped below baseline — see delta above. Baseline updates on next passing merge.")
    if "bootstrap_no_previous_result" in failed_reasons:
        out.append("- No baseline yet — will be set once this run passes.")
    return out


def _log_links_section(
    leg_summaries: list[dict[str, Any]],
    runtime_bucket_root: str | None,
    run_id: str | None,
) -> list[str]:
    out = ["", "**Logs**", ""]
    has_any = False
    if runtime_bucket_root and run_id:
        status_uri = f"{runtime_bucket_root.rstrip('/')}/triggers/status/{run_id}.json"
        status_url = gcs_uri_to_console_url(status_uri)
        if status_url:
            out.append(f"- Run status: [open in GCS]({status_url})")
            has_any = True
    for summary in leg_summaries:
        project = summary.get("project_id", "?")
        bmt_id = summary.get("bmt_id", "?")
        uri = (summary.get("ci_verdict_uri") or "").strip()
        if uri.endswith("ci_verdict.json"):
            logs_uri = uri[: -len("ci_verdict.json")] + "logs/"
            console_url = gcs_uri_to_console_url(logs_uri)
            if console_url:
                out.append(f"- {project}.{bmt_id}: [logs]({console_url})")
                has_any = True
    if not has_any:
        out.append("_No log links available._")
    return out


def render_results_table(
    leg_summaries: list[dict[str, Any]],
    _aggregate: dict[str, Any],
    *,
    run_id: str | None = None,
    runtime_bucket_root: str | None = None,
    log_dump_url: str | None = None,
) -> str:
    """Render final BMT Gate output: pass/fail, scores, logs (per docs/architecture.md).

    Args:
        leg_summaries: List of manager summary dicts
        aggregate: Aggregate verdict dict with state/decision/reasons
        run_id: Optional workflow run id for "Run status" GCS link
        runtime_bucket_root: Optional gs://bucket/runtime for building status/logs URLs
        log_dump_url: Optional signed URL for log dump; when set appends "Log dump (link expires in 3 days): ..."

    Returns:
        Markdown for Check Run summary (verdict table + GCS log links)
    """
    lines = ["**Pass/fail, scores, logs**", ""]
    lines.append("| Project | Test suite | Verdict | Score | Baseline | Delta | Reason | Duration |")
    lines.append("|---------|------------|---------|-------|----------|-------|--------|----------:|")
    for summary in leg_summaries:
        lines.append(_leg_row_line(summary))
    failed_reasons = [
        summary.get("reason_code", "") or "" for summary in leg_summaries if not summary_dict_leg_passed(summary)
    ]
    lines.extend(_failure_guidance_lines(leg_summaries, failed_reasons))
    lines.extend(_log_links_section(leg_summaries, runtime_bucket_root, run_id))
    if log_dump_url:
        lines.extend(["", f"Log dump (link expires in 3 days): {log_dump_url}"])
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

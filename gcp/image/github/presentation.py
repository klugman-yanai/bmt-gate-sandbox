from __future__ import annotations

from dataclasses import dataclass, field

from gcp.image.config.bmt_domain_status import BmtLegStatus, BmtProgressStatus, leg_status_is_pass
from gcp.image.config.status import CheckConclusion
from gcp.image.github.duration_format import format_duration_seconds

_MARKER = "<!-- bmt-gate-comment -->"

REASON_LABELS: dict[str, str] = {
    "score_below_last": "score dropped below baseline",
    "score_above_last": "score exceeded the allowed baseline",
    "score_gte_last": "score met or exceeded baseline",
    "score_lte_last": "score stayed within the expected baseline",
    "bootstrap_no_previous_result": "first run — baseline established",
    "runner_failures": "the runner exited with a failure",
    "runner_timeout": "the runner timed out",
    "demo_force_pass": "forced pass override (demo mode)",
    "bootstrap_without_baseline": "first run — baseline established",
    "runner_case_failures": "runner crashed on one or more test files",
}


def comment_marker() -> str:
    return _MARKER


def _gcp_console_link(url: str) -> str:
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">BMT Cloud Job (GCP Console)</a>'


def human_reason(reason_code: str) -> str:
    return REASON_LABELS.get(reason_code, reason_code.replace("_", " ").strip() or "unknown failure")


@dataclass(frozen=True, slots=True)
class LiveLinks:
    workflow_execution_url: str
    log_dump_url: str | None = None


@dataclass(frozen=True, slots=True)
class ProgressBmtRow:
    project: str
    bmt: str
    status: str
    duration_sec: int | None = None
    #: Set when this leg has written `summary.json` (completed task); drives Score column.
    aggregate_score: float | None = None
    execution_mode_used: str = ""
    cases_detail: str = ""


@dataclass(frozen=True, slots=True)
class FinalBmtRow:
    project: str
    bmt: str
    status: str
    aggregate_score: float
    reason_code: str
    duration_sec: int | None = None
    execution_mode_used: str = ""
    cases_detail: str = ""


@dataclass(frozen=True, slots=True)
class StartedCommentView:
    head_sha: str
    links: LiveLinks


@dataclass(frozen=True, slots=True)
class FinalCommentView:
    head_sha: str
    state: str
    links: LiveLinks
    failed_bmts: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CheckProgressView:
    completed_count: int
    total_count: int
    elapsed_sec: int | None
    eta_sec: int | None
    links: LiveLinks
    bmts: list[ProgressBmtRow]


@dataclass(frozen=True, slots=True)
class CheckFinalView:
    state: str
    links: LiveLinks
    bmts: list[FinalBmtRow]


def render_started_pr_comment(view: StartedCommentView) -> str:
    short_sha = view.head_sha[:7] or "unknown"
    lines = [
        comment_marker(),
        "",
        "## BMT Started",
        "",
        f"BMTs are running for `{short_sha}`.",
        "",
        f"- Status: `{BmtProgressStatus.PENDING.value}`",
    ]
    if view.links.workflow_execution_url:
        lines.append(f"- Live runtime: {_gcp_console_link(view.links.workflow_execution_url)}")
    lines.append("- Detailed progress: see the **BMT Gate** check")
    return "\n".join(lines)


def render_final_pr_comment(view: FinalCommentView) -> str:
    short_sha = view.head_sha[:7] or "unknown"
    if view.state == CheckConclusion.SUCCESS.value:
        lines = [
            comment_marker(),
            "",
            "## BMT Passed",
            "",
            f"BMTs passed for `{short_sha}`.",
            "",
            f"- Status: `{CheckConclusion.SUCCESS.value}`",
            "- Full details: see the **BMT Gate** check",
        ]
        if view.links.workflow_execution_url:
            lines.insert(-1, f"- Live runtime: {_gcp_console_link(view.links.workflow_execution_url)}")
        return "\n".join(lines)

    lines = [
        comment_marker(),
        "",
        "## BMT Failed",
        "",
        f"One or more BMTs failed for `{short_sha}`.",
        "",
        f"- Status: `{CheckConclusion.FAILURE.value}`",
    ]
    if view.links.workflow_execution_url:
        lines.append(f"- Live runtime: {_gcp_console_link(view.links.workflow_execution_url)}")
    if view.links.log_dump_url:
        lines.append(f"- Failure log dump: [3-day link]({view.links.log_dump_url})")
    lines.append("- Full details: see the **BMT Gate** check")
    if view.failed_bmts:
        lines.extend(["", "Failed BMTs:"])
        lines.extend(f"- `{bmt}`: {reason}" for bmt, reason in view.failed_bmts)
    return "\n".join(lines)


def _score_cell_for_check(*, aggregate_score: float | None, execution_mode_used: str, leg_done: bool) -> str:
    """Format score for GitHub Checks tab (avoid misleading 0.00 for mock runs)."""
    if execution_mode_used == "mock":
        return "— (mock)"
    if leg_done and aggregate_score is not None:
        return f"{aggregate_score:.2f}"
    return "—"


def render_progress_check_output(view: CheckProgressView) -> dict[str, str]:
    lines = [
        "**BMTs are running**",
        "",
        f"- Progress: `{view.completed_count}/{view.total_count}` complete",
        f"- Elapsed: `{_format_duration(view.elapsed_sec)}`",
        f"- ETA: `{_format_eta(view.eta_sec)}`",
    ]
    if view.links.workflow_execution_url:
        lines.append(f"- Live runtime: {_gcp_console_link(view.links.workflow_execution_url)}")
    lines.extend(
        [
            "",
            "| Project | BMT | Status | Score | Cases | Duration |",
            "|---------|-----|--------|-------|-------|----------|",
        ]
    )
    for row in view.bmts:
        leg_done = row.status in (BmtLegStatus.PASS.value, BmtLegStatus.FAIL.value)
        score_s = _score_cell_for_check(
            aggregate_score=row.aggregate_score,
            execution_mode_used=row.execution_mode_used,
            leg_done=leg_done,
        )
        lines.append(
            f"| {row.project} | {row.bmt} | {_progress_status_label(row.status)} | {score_s} | {row.cases_detail or '—'} | {_format_duration(row.duration_sec)} |"
        )
    return {
        "title": f"BMT Running: {view.completed_count}/{view.total_count} complete",
        "summary": "\n".join(lines),
    }


def _final_check_table_lines(view: CheckFinalView) -> list[str]:
    header = [
        "",
        "| Project | BMT | Status | Score | Cases | Reason | Duration |",
        "|---------|-----|--------|-------|-------|--------|----------|",
    ]
    body: list[str] = []
    for row in view.bmts:
        score_s = _score_cell_for_check(
            aggregate_score=row.aggregate_score,
            execution_mode_used=row.execution_mode_used,
            leg_done=True,
        )
        body.append(
            "| "
            + " | ".join(
                [
                    row.project,
                    row.bmt,
                    _final_status_label(row.status),
                    score_s,
                    row.cases_detail or "—",
                    human_reason(row.reason_code),
                    _format_duration(row.duration_sec),
                ]
            )
            + " |"
        )
    return header + body


def _final_check_failure_summary_lines(view: CheckFinalView) -> list[str]:
    if view.state == CheckConclusion.SUCCESS.value:
        return []
    failed_rows = [row for row in view.bmts if not leg_status_is_pass(row.status)]
    if not failed_rows:
        return []
    out = ["", "### Failure summary", ""]
    out.extend(f"- `{row.bmt}`: {human_reason(row.reason_code)}" for row in failed_rows)
    return out


def render_final_check_output(view: CheckFinalView) -> dict[str, str]:
    is_success = view.state == CheckConclusion.SUCCESS.value
    lines = [
        "**All BMTs passed**" if is_success else "**One or more BMTs failed**",
        "",
        f"- Result: `{CheckConclusion.SUCCESS.value if is_success else CheckConclusion.FAILURE.value}`",
    ]
    if view.links.workflow_execution_url:
        lines.append(f"- Live runtime: {_gcp_console_link(view.links.workflow_execution_url)}")
    if view.links.log_dump_url:
        lines.append(f"- Log dump (expires in 3 days): [open]({view.links.log_dump_url})")
    lines.extend(_final_check_table_lines(view))
    lines.extend(_final_check_failure_summary_lines(view))
    return {
        "title": f"BMT Complete: {'PASS' if is_success else 'FAIL'}",
        "summary": "\n".join(lines),
    }


def _progress_status_label(status: str) -> str:
    labels = {
        BmtLegStatus.PASS.value: "Complete",
        BmtLegStatus.FAIL.value: "Failed",
        "failure": "Failed",
        BmtProgressStatus.RUNNING.value: "Running",
        BmtProgressStatus.PENDING.value: "Pending",
    }
    return labels.get(status, status.title())


def _final_status_label(status: str) -> str:
    return "PASS" if leg_status_is_pass(status) else "FAIL"


def _format_eta(seconds: int | None) -> str:
    return _format_duration(seconds) if seconds is not None else "unknown"


def _format_duration(seconds: int | None) -> str:
    return format_duration_seconds(seconds)

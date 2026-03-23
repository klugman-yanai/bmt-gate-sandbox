from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gcp.image.config.bmt_domain_status import BmtLegStatus, BmtProgressStatus, leg_status_is_pass
from gcp.image.config.status import CheckConclusion
from gcp.image.github.duration_format import format_duration_seconds
from gcp.image.github.github_checks import CheckRunOutput

_MARKER = "<!-- bmt-gate-comment -->"

# Copy shown in GitHub Checks / PR comments (single module to keep wording aligned).
CHECK_COPY_GATE = "BMT Gate"
CHECK_TITLE_PASS = "PASS"
CHECK_TITLE_FAIL = "FAIL"
EM_DASH = "—"
MISSING_SCORE = "—"
MOCK_SCORE_PLACEHOLDER = "— (mock)"
UNKNOWN_SHORT_SHA = "unknown"
_ETA_UNKNOWN = "unknown"

_BOOTSTRAP_FIRST_RUN = "first run — baseline established"
REASON_LABELS: dict[str, str] = {
    "score_below_last": "score dropped below baseline",
    "score_above_last": "score exceeded the allowed baseline",
    "score_gte_last": "score met or exceeded baseline",
    "score_lte_last": "score stayed within the expected baseline",
    "bootstrap_no_previous_result": _BOOTSTRAP_FIRST_RUN,
    "runner_failures": "the runner exited with a failure",
    "runner_timeout": "the runner timed out",
    "demo_force_pass": "forced pass override (demo mode)",
    "bootstrap_without_baseline": _BOOTSTRAP_FIRST_RUN,
    "runner_case_failures": "runner crashed on one or more test files",
    "no_dataset_cases": "no test cases were produced (empty dataset or execution produced no rows)",
    "plugin_execute_failed": "the BMT plugin failed during execute (setup, imports, or orchestration)",
}


def comment_marker() -> str:
    return _MARKER


def _gcp_console_link(url: str) -> str:
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">BMT Cloud Job (GCP Console)</a>'


def human_reason(reason_code: str) -> str:
    """Map domain reason codes to operator-facing text. Unknown codes are explicit (no fake prose)."""
    if reason_code in REASON_LABELS:
        return REASON_LABELS[reason_code]
    cleaned = reason_code.strip()
    if not cleaned:
        return "empty reason code"
    return f"unmapped reason code: `{cleaned}`"


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
    #: Mirrors :attr:`LegSummary.score.extra` (e.g. ``unavailable`` when coordinator could not load summary).
    score_extra: dict[str, Any] = field(default_factory=dict)


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
    short_sha = view.head_sha[:7] or UNKNOWN_SHORT_SHA
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
    lines.append(f"- Detailed progress: see the **{CHECK_COPY_GATE}** check")
    return "\n".join(lines)


def render_final_pr_comment(view: FinalCommentView) -> str:
    short_sha = view.head_sha[:7] or UNKNOWN_SHORT_SHA
    if view.state == CheckConclusion.SUCCESS.value:
        lines = [
            comment_marker(),
            "",
            "## BMT Passed",
            "",
            f"BMTs passed for `{short_sha}`.",
            "",
            f"- Status: `{CheckConclusion.SUCCESS.value}`",
            f"- Full details: see the **{CHECK_COPY_GATE}** check",
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
    lines.append(f"- Full details: see the **{CHECK_COPY_GATE}** check")
    if view.failed_bmts:
        lines.extend(["", "Failed BMTs:"])
        lines.extend(f"- `{bmt}`: {reason}" for bmt, reason in view.failed_bmts)
    return "\n".join(lines)


def _score_cell_for_check(
    *,
    aggregate_score: float | None,
    execution_mode_used: str,
    leg_done: bool,
    score_extra: dict[str, Any] | None = None,
) -> str:
    """Format score for GitHub Checks tab (avoid misleading 0.00 for mock runs)."""
    if score_extra and score_extra.get("unavailable"):
        return MISSING_SCORE
    if execution_mode_used == "mock":
        return MOCK_SCORE_PLACEHOLDER
    if leg_done and aggregate_score is not None:
        return f"{aggregate_score:.2f}"
    return MISSING_SCORE


def _md_table_cell(value: object) -> str:
    """Avoid broken pipe tables when project/bmt/cases contain ``|`` or newlines."""
    s = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\n", " ").replace("|", "·")


_LEGACY_STATUS_FAILURE = "failure"
_PROGRESS_STATUS_LABELS: dict[str, str] = {
    BmtLegStatus.PASS.value: "Complete",
    BmtLegStatus.FAIL.value: "Failed",
    BmtProgressStatus.RUNNING.value: "Running",
    BmtProgressStatus.PENDING.value: "Pending",
}


def _progress_status_label(status: str) -> str:
    if status == _LEGACY_STATUS_FAILURE:
        return "Failed"
    return _PROGRESS_STATUS_LABELS.get(status, status.title())


def _progress_table_markdown(view: CheckProgressView) -> str:
    lines = [
        "| Project | BMT | Status | Score | Cases | Duration |",
        "|---------|-----|--------|-------|-------|----------|",
    ]
    for row in view.bmts:
        leg_done = row.status in (BmtLegStatus.PASS.value, BmtLegStatus.FAIL.value)
        score_s = _score_cell_for_check(
            aggregate_score=row.aggregate_score,
            execution_mode_used=row.execution_mode_used,
            leg_done=leg_done,
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_table_cell(row.project),
                    _md_table_cell(row.bmt),
                    _progress_status_label(row.status),
                    score_s,
                    _md_table_cell(row.cases_detail or EM_DASH),
                    _format_duration(row.duration_sec),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _final_check_table_markdown(view: CheckFinalView) -> str:
    lines = [
        "| Project | BMT | Status | Score | Cases | Reason | Duration |",
        "|---------|-----|--------|-------|-------|--------|----------|",
    ]
    for row in view.bmts:
        score_s = _score_cell_for_check(
            aggregate_score=row.aggregate_score,
            execution_mode_used=row.execution_mode_used,
            leg_done=True,
            score_extra=row.score_extra,
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_table_cell(row.project),
                    _md_table_cell(row.bmt),
                    _final_status_label(row.status),
                    score_s,
                    _md_table_cell(row.cases_detail or EM_DASH),
                    _md_table_cell(human_reason(row.reason_code)),
                    _format_duration(row.duration_sec),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def render_progress_check_output(view: CheckProgressView) -> CheckRunOutput:
    """Return check output: skimmable ``summary``, full BMT table in ``text`` (GitHub Checks API)."""
    summary_lines = [
        "**BMTs are running**",
        "",
        f"- Progress: `{view.completed_count}/{view.total_count}` complete",
        f"- Elapsed: `{_format_duration(view.elapsed_sec)}`",
        f"- ETA: `{_format_eta(view.eta_sec)}`",
    ]
    if view.links.workflow_execution_url:
        summary_lines.append(f"- Live runtime: {_gcp_console_link(view.links.workflow_execution_url)}")
    table = _progress_table_markdown(view)
    return {
        "title": f"BMT Running: {view.completed_count}/{view.total_count} complete",
        "summary": "\n".join(summary_lines),
        "text": table,
    }


def _final_check_failure_summary_lines(view: CheckFinalView) -> list[str]:
    if view.state == CheckConclusion.SUCCESS.value:
        return []
    failed_rows = [row for row in view.bmts if not leg_status_is_pass(row.status)]
    if not failed_rows:
        return []
    out = ["", "### Failure summary", ""]
    out.extend(f"- `{row.bmt}`: {human_reason(row.reason_code)}" for row in failed_rows)
    return out


def render_final_check_output(view: CheckFinalView) -> CheckRunOutput:
    """Return check output: skimmable ``summary``, full results table in ``text`` (GitHub Checks API)."""
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
    lines.extend(_final_check_failure_summary_lines(view))
    return {
        "title": f"BMT Complete: {CHECK_TITLE_PASS if is_success else CHECK_TITLE_FAIL}",
        "summary": "\n".join(lines),
        "text": _final_check_table_markdown(view),
    }


def _final_status_label(status: str) -> str:
    return "PASS" if leg_status_is_pass(status) else "FAIL"


def _format_eta(seconds: int | None) -> str:
    return _format_duration(seconds) if seconds is not None else _ETA_UNKNOWN


def _format_duration(seconds: int | None) -> str:
    return format_duration_seconds(seconds)

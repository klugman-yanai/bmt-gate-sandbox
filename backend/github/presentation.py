from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from backend.config.bmt_domain_status import BmtLegStatus, BmtProgressStatus, leg_status_is_pass
from backend.config.status import CheckConclusion
from backend.github.duration_format import format_duration_seconds
from backend.github.github_checks import CheckRunOutput

# ``case_outcomes[].status`` wire value for a passing file (matches ``CaseStatus``); never shown as the word “ok” to operators.
_CASE_OUTCOME_STATUS_PASSED = "ok"

_MARKER = "<!-- bmt-gate-comment -->"

# Copy shown in GitHub Checks / PR comments (single module to keep wording aligned).
CHECK_COPY_GATE = "BMT Gate"
CHECK_TITLE_PASS = "PASS"
CHECK_TITLE_FAIL = "FAIL"
EM_DASH = "—"
MISSING_SCORE = "—"
MOCK_SCORE_PLACEHOLDER = "— (mock)"
UNKNOWN_SHORT_SHA = "unknown"
# GitHub check run API caps annotations per request; overflow remains in Markdown.
MAX_GITHUB_CHECK_ANNOTATIONS = 50

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
    "runner_case_failures": "too many test files failed the runner (beyond configured grace)",
    "case_failures_within_grace": "one or more test files failed, within grace — gate still passed; see per-case details",
    "no_dataset_cases": "no test cases were produced (empty dataset or execution produced no rows)",
    "plugin_execute_failed": "the BMT plugin failed during execute (setup, imports, or orchestration)",
}


def comment_marker() -> str:
    return _MARKER


def _gcp_console_link(url: str) -> str:
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">Google Cloud Workflow execution</a>'


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
    workflow_run_id: str = ""
    handoff_run_url: str = ""
    gcs_bucket: str = ""


def _gcs_triggers_browser_url(bucket: str) -> str:
    """Console URL to browse ``triggers/`` under the stage bucket (project from console context)."""
    return f"https://console.cloud.google.com/storage/browser/{quote(bucket, safe='')}/triggers"


def correlation_section_markdown(links: LiveLinks) -> str:
    """Short operator block: run id, handoff Actions URL, GCS prefix (for PR comments and checks)."""
    lines: list[str] = []
    if links.workflow_run_id.strip():
        wid = links.workflow_run_id.strip()
        lines.append(
            f"- **BMT workflow_run_id** (GCS: `triggers/plans/{wid}.json`, `triggers/reporting/{wid}.json`): `{wid}`"
        )
    if links.handoff_run_url.strip():
        hu = links.handoff_run_url.strip()
        lines.append(f"- **GitHub handoff workflow run:** [open]({hu})")
    if links.gcs_bucket.strip():
        bu = links.gcs_bucket.strip()
        lines.append(f"- **GCS triggers folder:** [browse in console]({_gcs_triggers_browser_url(bu)})")
    if not lines:
        return ""
    return "\n".join(["", "### Debug / correlation", "", *lines])


def _append_correlation_pr(lines: list[str], links: LiveLinks) -> None:
    cm = correlation_section_markdown(links)
    if cm.strip():
        lines.append(cm.strip())


@dataclass(frozen=True, slots=True)
class ProgressBmtRow:
    project: str
    bmt: str
    status: str
    #: Wall seconds for this leg: final duration when :attr:`has_completed_summary` is True; otherwise
    #: from ``triggers/progress`` (often unset until the task finishes) — not used as a total-time
    #: estimate for ETA while the leg is still in flight.
    duration_sec: int | None = None
    #: True when ``triggers/summaries/...`` exists for this leg (terminal pass/fail for this run).
    has_completed_summary: bool = False
    #: Set when this BMT has written `summary.json` (completed task); drives the Avg. column.
    aggregate_score: float | None = None
    execution_mode_used: str = ""
    cases_detail: str = ""
    #: From ``score.extra.scoring_policy`` / verdict; used with arrows in the Avg. column; empty when unknown or mock.
    score_direction_label: str = ""


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
    score_direction_label: str = ""
    #: Per-case rows from ``metrics.case_outcomes`` when the plugin provides them; failure tables and annotations.
    case_outcomes: list[dict[str, Any]] = field(default_factory=list)


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
    #: Passing legs that had tolerated per-file failures (``max_grace_case_failures``).
    case_failure_warnings: list[tuple[str, str]] = field(default_factory=list)


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
    _append_correlation_pr(lines, view.links)
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
        if view.case_failure_warnings:
            lines.extend(
                [
                    "",
                    "**Note —** some benchmark files did not run cleanly (within configured grace):",
                    "",
                ]
            )
            lines.extend(f"- `{bmt}`: {msg}" for bmt, msg in view.case_failure_warnings)
        _append_correlation_pr(lines, view.links)
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
    _append_correlation_pr(lines, view.links)
    return "\n".join(lines)


def _scoring_policy_dict(extra: dict[str, Any]) -> dict[str, Any] | None:
    sp = extra.get("scoring_policy")
    return sp if isinstance(sp, dict) else None


def _default_success_in_words(scoring_policy: dict[str, Any]) -> str:
    hint = scoring_policy.get("score_direction_hint")
    if hint == "lower_better":
        return "Prefer lower numbers here. **Zero** is ideal when the counted events are unwanted (e.g. false alarms)."
    if hint == "higher_better":
        return "Prefer higher numbers here (per-file counts vs your baseline)."
    return "See this BMT's scoring policy for what the summary number means."


def _avg_column_direction_suffix(score_extra: dict[str, Any] | None, score_direction_label: str) -> str:
    """Compact direction marker for the Avg. column (Markdown-friendly)."""
    sp = _scoring_policy_dict(score_extra) if score_extra else None
    if isinstance(sp, dict):
        h = sp.get("score_direction_hint")
        if h == "lower_better":
            return "↓"
        if h == "higher_better":
            return "↑"
    lab = (score_direction_label or "").strip().lower()
    if "lower" in lab:
        return "↓"
    if "higher" in lab:
        return "↑"
    return ""


def run_context_blurb_markdown(rows: list[FinalBmtRow]) -> str:
    """Short context copy from ``score.extra.scoring_policy`` / ``reporting_hints`` (generic; no slug branching)."""
    if not rows:
        return ""
    has_policy = any(_scoring_policy_dict(r.score_extra) for r in rows)
    if len(rows) == 1 and not has_policy:
        return ""
    parts: list[str] = [
        "*Each BMT row stands alone. Pass or fail vs your stored baseline is decided **per test file**. "
        "**Avg.** is one summary value for that BMT (often an average across files that passed). "
        "**Tests** is how many test files passed. "
        "Compare **Avg.** within the same BMT over time rather than across unrelated BMT rows.*",
    ]
    if len(rows) > 1:
        parts.append("*Different BMT rows may measure different things; treat the numbers as separate.*")
    parts.append("*On **Avg.**: ↓ = lower is better for that row · ↑ = higher is better.*")
    if has_policy:
        parts.append("")
        for r in rows:
            sp = _scoring_policy_dict(r.score_extra)
            if not sp:
                continue
            hints_raw = sp.get("reporting_hints")
            hints: dict[str, Any] = hints_raw if isinstance(hints_raw, dict) else {}
            sw = hints.get("success_in_words")
            if isinstance(sw, str) and sw.strip():
                body = sw.strip()
            else:
                body = _default_success_in_words(sp)
            msl = hints.get("metric_short_label")
            if isinstance(msl, str) and msl.strip():
                body = f"{body} — *{msl.strip()}*"
            elif isinstance(sp.get("primary_metric"), str) and str(sp["primary_metric"]).strip():
                body = f"{body} — *metric `{sp['primary_metric']}`*"
            parts.append(f"- **`{r.project}` / `{r.bmt}`:** {body}")
    parts.append("")
    return "\n".join(parts).strip() + "\n"


def how_to_read_this_run_markdown(rows: list[FinalBmtRow]) -> str:
    """Alias for :func:`run_context_blurb_markdown` (older name)."""
    return run_context_blurb_markdown(rows)


def _score_cell_for_check(
    *,
    aggregate_score: float | None,
    execution_mode_used: str,
    leg_done: bool,
    score_extra: dict[str, Any] | None = None,
    score_direction_label: str = "",
) -> str:
    """Format the Avg. column for GitHub Checks (avoid misleading 0.00 for mock runs)."""
    if score_extra and score_extra.get("unavailable"):
        return MISSING_SCORE
    if execution_mode_used == "mock":
        return MOCK_SCORE_PLACEHOLDER
    if leg_done and aggregate_score is not None:
        cell = f"{aggregate_score:.2f}"
        suffix = _avg_column_direction_suffix(score_extra, score_direction_label)
        if suffix:
            cell = f"{cell} {suffix}"
        return cell
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


def _format_progress_run_so_far_cell(row: ProgressBmtRow) -> str:
    """Duration column while in-flight: label partial wall time so it is not read as final."""
    base = _format_duration(row.duration_sec)
    if row.has_completed_summary:
        return base
    if row.duration_sec is not None and row.duration_sec >= 0:
        return f"{base} *(running)*"
    return base


def _progress_table_markdown(view: CheckProgressView) -> str:
    lines = [
        "| Project | BMT | Status | Avg. | Tests | Run so far |",
        "|---------|-----|--------|------|-------|------------|",
    ]
    for row in view.bmts:
        leg_done = row.status in (BmtLegStatus.PASS.value, BmtLegStatus.FAIL.value)
        score_s = _score_cell_for_check(
            aggregate_score=row.aggregate_score,
            execution_mode_used=row.execution_mode_used,
            leg_done=leg_done,
            score_extra=None,
            score_direction_label=row.score_direction_label,
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
                    _format_progress_run_so_far_cell(row),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _final_check_table_markdown(view: CheckFinalView) -> str:
    lines = [
        "| Project | BMT | Status | Avg. | Tests | Reason | Duration |",
        "|---------|-----|--------|------|-------|--------|----------|",
    ]
    for row in view.bmts:
        score_s = _score_cell_for_check(
            aggregate_score=row.aggregate_score,
            execution_mode_used=row.execution_mode_used,
            leg_done=True,
            score_extra=row.score_extra,
            score_direction_label=row.score_direction_label,
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


def github_check_final_title(*, is_success: bool) -> str:
    """Short check-run title when the gate has finished (keep in sync with :func:`render_final_check_output`)."""
    return f"Gate {CHECK_TITLE_PASS}" if is_success else f"Gate {CHECK_TITLE_FAIL}"


def _progress_finish_estimate_markdown(view: CheckProgressView) -> str:
    if view.eta_sec is not None:
        return (
            f"About **{_format_duration(view.eta_sec)}** remaining — rough wall-clock estimate from "
            "prior runs and **parallel** legs still in flight."
        )
    return (
        "**Not estimated yet** — needs snapshot history from earlier runs, or at least one **finished** leg "
        "in this run to anchor timing."
    )


def _progress_bmt_clock_markdown(view: CheckProgressView) -> str | None:
    if view.elapsed_sec is None:
        return None
    return (
        f"**{_format_duration(view.elapsed_sec)}** on the **BMT clock** (since this gate started reporting in "
        "GCS). *This is not the same as the GitHub Actions job timer shown above.*"
    )


def _progress_check_summary_markdown(view: CheckProgressView) -> str:
    total = view.total_count
    done = view.completed_count
    lines: list[str] = [
        "### Progress",
        "",
        f"**{done}** of **{total}** BMT legs finished.",
        "",
        "### Finish estimate",
        "",
        _progress_finish_estimate_markdown(view),
        "",
    ]
    clock = _progress_bmt_clock_markdown(view)
    if clock is not None:
        lines.extend(["### BMT clock", "", clock, ""])
    if view.links.workflow_execution_url:
        lines.extend(["### Live execution", "", _gcp_console_link(view.links.workflow_execution_url), ""])
    cm = correlation_section_markdown(view.links)
    if cm.strip():
        lines.extend([cm.strip(), ""])
    lines.extend(
        [
            "---",
            "",
            "*Per-leg **Avg.**, **Tests**, and direction markers (↑/↓) appear when that leg completes. "
            "The **Run so far** column may show partial wall time while a leg is still running.*",
        ]
    )
    return "\n".join(lines)


def _progress_check_text_markdown(view: CheckProgressView) -> str:
    intro = (
        "### Legs\n"
        "\n"
        "*Complete* / *Failed* means the leg wrote a final summary. "
        "*Running* / *Pending* means work is still in progress.\n"
    )
    return intro + "\n" + _progress_table_markdown(view)


def render_progress_check_output(view: CheckProgressView) -> CheckRunOutput:
    """Return check output: skimmable ``summary``, full BMT table in ``text`` (GitHub Checks API)."""
    return {
        "title": f"In progress · {view.completed_count}/{view.total_count}",
        "summary": _progress_check_summary_markdown(view),
        "text": _progress_check_text_markdown(view),
    }


def _annotation_path_segment(raw: str) -> str:
    """Synthetic repo path segment for Check annotations (avoid slashes / control chars)."""
    s = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    for ch in ("/", "\\", "\x00"):
        s = s.replace(ch, "_")
    return s[:200] if len(s) > 200 else s


def github_check_annotations_from_final_rows(rows: list[FinalBmtRow]) -> list[dict[str, Any]]:
    """Build GitHub Checks ``output.annotations`` for failed cases (capped)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        for oc in row.case_outcomes:
            if len(out) >= MAX_GITHUB_CHECK_ANNOTATIONS:
                return out
            if oc.get("status") == _CASE_OUTCOME_STATUS_PASSED:
                continue
            cid = str(oc.get("case_id", ""))
            msg = str(oc.get("error", "")).strip()
            if len(msg) > 8000:
                msg = msg[:7997] + "..."
            path = "/".join(
                (
                    "bmt",
                    _annotation_path_segment(row.project),
                    _annotation_path_segment(row.bmt),
                    _annotation_path_segment(cid),
                )
            )
            level = "warning" if leg_status_is_pass(row.status) else "failure"
            out.append(
                {
                    "path": path,
                    "start_line": 1,
                    "end_line": 1,
                    "annotation_level": level,
                    "message": msg or "(no error message)",
                }
            )
    return out


def tolerated_case_failures_notice_markdown(rows: list[FinalBmtRow]) -> str:
    """One-line bullets for passing legs that still had runner/parser failures (within grace)."""
    parts: list[str] = []
    for row in rows:
        if not leg_status_is_pass(row.status):
            continue
        failed = [c for c in row.case_outcomes if c.get("status") != _CASE_OUTCOME_STATUS_PASSED]
        if not failed:
            continue
        ids = ", ".join(f"`{_md_table_cell(c.get('case_id', ''))}`" for c in failed)
        parts.append(f"- **`{row.project}` / `{row.bmt}`:** {len(failed)} file(s): {ids}")
    return "\n".join(parts).strip()


def per_case_failure_markdown(rows: list[FinalBmtRow]) -> str:
    """Markdown tables for cases that did not pass (execution failures stay visible)."""
    blocks: list[str] = []
    for row in rows:
        failed = [c for c in row.case_outcomes if c.get("status") != _CASE_OUTCOME_STATUS_PASSED]
        if not failed:
            continue
        blocks.append(f"#### `{row.project}` / `{row.bmt}`")
        lines = ["| Case | Error | Log |", "| --- | --- | --- |"]
        for c in failed:
            cid = _md_table_cell(c.get("case_id", ""))
            err = _md_table_cell(c.get("error", ""))
            logn = _md_table_cell(c.get("log_name", ""))
            lines.append(f"| {cid} | {err} | {logn} |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip()


def multi_leg_score_scope_markdown(row_count: int) -> str:
    """Fallback scope line; prefer :func:`run_context_blurb_markdown` when ``FinalBmtRow`` data exists."""
    if row_count <= 1:
        return ""
    return "*Different BMT rows may use different metrics and directions; raw **Avg.** values are not automatically comparable.*"


def links_markdown(links: LiveLinks) -> str:
    """Shared Links block for check summary + body text (GitHub UI may hide summary)."""
    parts: list[str] = ["### Links", ""]
    if links.workflow_execution_url:
        parts.append(f"- **Google Cloud Workflow:** {_gcp_console_link(links.workflow_execution_url)}")
    if links.log_dump_url:
        parts.append(f"- **Failure log bundle** (expires in 3 days): [open]({links.log_dump_url})")
    if not links.workflow_execution_url and not links.log_dump_url:
        parts.append("- *(no external links for this run)*")
    cm = correlation_section_markdown(links)
    if cm.strip():
        parts.append(cm.strip())
    return "\n".join(parts)


def _final_check_failure_summary_lines(view: CheckFinalView) -> list[str]:
    if view.state == CheckConclusion.SUCCESS.value:
        return []
    failed_rows = [row for row in view.bmts if not leg_status_is_pass(row.status)]
    if not failed_rows:
        return []
    out = ["", "### Failure summary", ""]
    out.extend(f"- `{row.bmt}`: {human_reason(row.reason_code)}" for row in failed_rows)
    return out


def _final_bmt_row_from_summary_dict(d: dict[str, Any]) -> FinalBmtRow:
    """Map coordinator/gate ``summary.json``-shaped dicts into :class:`FinalBmtRow`."""
    score_raw = d.get("score")
    score: dict[str, Any] = score_raw if isinstance(score_raw, dict) else {}
    metrics_raw = score.get("metrics")
    metrics: dict[str, Any] = metrics_raw if isinstance(metrics_raw, dict) else {}
    raw_cases = metrics.get("case_outcomes")
    case_outcomes = [c for c in raw_cases if isinstance(c, dict)] if isinstance(raw_cases, list) else []
    extra_raw = score.get("extra")
    extra: dict[str, Any] = dict(extra_raw) if isinstance(extra_raw, dict) else {}
    agg = score.get("aggregate_score")
    aggregate_score = float(agg) if isinstance(agg, (int, float)) else 0.0
    return FinalBmtRow(
        project=str(d.get("project", "")),
        bmt=str(d.get("bmt_slug") or d.get("bmt", "")),
        status=str(d.get("status", "")),
        aggregate_score=aggregate_score,
        reason_code=str(d.get("reason_code", "")),
        duration_sec=d.get("duration_sec") if isinstance(d.get("duration_sec"), int) else None,
        execution_mode_used=str(d.get("execution_mode_used", "")),
        cases_detail="",
        score_extra=extra,
        score_direction_label=str(d.get("score_direction_label", "")),
        case_outcomes=case_outcomes,
    )


def render_results_table(
    leg_summaries: list[dict[str, Any]],
    verdict: dict[str, Any],
    *,
    run_id: str,
    runtime_bucket_root: str,
    log_dump_url: str | None,
) -> str:
    """Skimmable GitHub Check Run **summary** Markdown from serialized leg rows (gate / legacy paths)."""
    vm = str(verdict.get("state", "")).upper()
    check_state = CheckConclusion.SUCCESS.value if vm == "PASS" else CheckConclusion.FAILURE.value
    view = CheckFinalView(
        state=check_state,
        links=LiveLinks(workflow_execution_url="", log_dump_url=log_dump_url),
        bmts=[_final_bmt_row_from_summary_dict(s) for s in leg_summaries],
    )
    out = render_final_check_output(view)
    summary = str(out.get("summary", ""))
    tail: list[str] = []
    if run_id.strip():
        tail.append(f"- Run id: `{run_id.strip()}`")
    if runtime_bucket_root.strip():
        tail.append(f"- Runtime bucket root: `{runtime_bucket_root.strip()}`")
    if not tail:
        return summary
    return summary + "\n\n### Run metadata\n\n" + "\n".join(tail)


def render_final_check_output(view: CheckFinalView) -> CheckRunOutput:
    """Return check output: skimmable ``summary``, full results table in ``text`` (GitHub Checks API)."""
    is_success = view.state == CheckConclusion.SUCCESS.value
    result_word = "passed" if is_success else "failed"
    gh_state = CheckConclusion.SUCCESS.value if is_success else CheckConclusion.FAILURE.value

    lines = [
        "### Result",
        "",
        f"**{result_word.upper()}** — GitHub conclusion `{gh_state}`.",
        "",
        "All BMT legs met the gate."
        if is_success
        else "At least one BMT leg did not meet the gate; see the failure summary and the full table below.",
        "",
    ]
    lines.append(links_markdown(view.links))
    lines.extend(_final_check_failure_summary_lines(view))
    if is_success:
        grace_notice = tolerated_case_failures_notice_markdown(view.bmts)
        if grace_notice:
            lines.extend(
                [
                    "",
                    "### Heads-up: some files failed (within grace)",
                    "",
                    "The gate **passed**, but one or more inputs hit runner or log parse issues. "
                    "Details are in **Per-case failures** below and as check annotations.",
                    "",
                    grace_notice,
                ]
            )
    blurb_md = run_context_blurb_markdown(view.bmts)
    text_parts: list[str] = []
    text_parts.append(links_markdown(view.links).rstrip())
    if blurb_md:
        text_parts.append(blurb_md.rstrip())
    else:
        scope_md = multi_leg_score_scope_markdown(len(view.bmts))
        if scope_md:
            text_parts.append(scope_md.rstrip())
    text_parts.append("### Per-leg results\n\n" + _final_check_table_markdown(view))
    failure_md = per_case_failure_markdown(view.bmts)
    if failure_md:
        text_parts.extend(["", "### Per-case failures", "", failure_md])
    annotations = github_check_annotations_from_final_rows(view.bmts)
    out: dict[str, Any] = {
        "title": github_check_final_title(is_success=is_success),
        "summary": "\n".join(lines),
        "text": "\n\n".join(text_parts),
    }
    if annotations:
        out["annotations"] = annotations
    return out  # type: ignore[return-value]


def _final_status_label(status: str) -> str:
    return "PASS" if leg_status_is_pass(status) else "FAIL"


def _format_duration(seconds: int | None) -> str:
    return format_duration_seconds(seconds)

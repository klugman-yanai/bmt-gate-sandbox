from __future__ import annotations

import html
import os
from dataclasses import dataclass, field
from typing import Any

from runtime.config import constants as runtime_constants
from runtime.config.bmt_domain_status import BmtLegStatus, BmtProgressStatus, leg_status_is_pass
from runtime.config.status import CheckConclusion
from runtime.github.duration_format import format_duration_seconds
from runtime.github.github_checks import CheckRunOutput

# ``case_outcomes[].status`` wire value for a passing file (matches ``CaseStatus``); never shown as the word “ok” to operators.
_CASE_OUTCOME_STATUS_PASSED = "ok"

_MARKER = "<!-- bmt-gate-comment -->"

# Copy shown in GitHub Checks / PR comments (single module to keep wording aligned).
CHECK_COPY_GATE = "BMT Gate"
CHECK_TITLE_PASS = "PASS"
CHECK_TITLE_FAIL = "FAIL"
EM_DASH = "—"
MISSING_SCORE = "—"
UNKNOWN_SHORT_SHA = "unknown"
_ETA_UNKNOWN = "unknown"
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
    "demo_force_pass": "force pass is currently active, merge unblock with no cloud run job execution",
    "bootstrap_without_baseline": _BOOTSTRAP_FIRST_RUN,
    "runner_case_failures": "runner crashed on one or more test files",
    "no_successful_cases": "runner crashed on all test files",
    "no_dataset_cases": "no test cases were produced (empty dataset or execution produced no rows)",
    "plugin_execute_failed": "the BMT plugin failed during execute (setup, imports, or orchestration)",
    "all_zero_keyword_hits_warn": "all keyword-hit counters were zero (warning only — PR not blocked)",
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
    #: From ``score.extra.scoring_policy`` / verdict; used with arrows in the Avg. column; empty when unknown.
    score_direction_label: str = ""
    #: Mirrors :attr:`LegSummary.score.extra` for completed legs (avg. column hints).
    score_extra: dict[str, Any] = field(default_factory=dict)
    #: From ``metrics.case_outcomes`` when the leg has finished and the plugin recorded per-file rows.
    case_outcomes: list[dict[str, Any]] = field(default_factory=list)


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
    force_pass_active: bool = False


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


def check_run_tab_refresh_hint_bullet() -> str:
    """PR-comment bullet describing how often the BMT Gate check body is published.

    Uses :data:`runtime.config.constants.BMT_CHECK_RUN_DETAIL_PUBLISH_INTERVAL_SEC_DEFAULT`
    and optional override ``ENV_BMT_CHECK_RUN_DETAIL_PUBLISH_INTERVAL_SEC`` so copy stays
    accurate when publish cadence changes.
    """
    raw = (os.environ.get(runtime_constants.ENV_BMT_CHECK_RUN_DETAIL_PUBLISH_INTERVAL_SEC) or "").strip()
    interval = runtime_constants.BMT_CHECK_RUN_DETAIL_PUBLISH_INTERVAL_SEC_DEFAULT
    if raw:
        try:
            parsed = int(raw, 10)
        except ValueError:
            parsed = -1
        if parsed >= 0:
            interval = parsed
    if interval > 0:
        every = format_duration_seconds(interval)
        return f"- **Checks tab:** live run detail is published at most every **{every}** while BMT legs are in flight."
    return (
        "- **Checks tab:** live run detail is published when **each leg starts** and again when **that leg finishes** "
        "(milestone updates only, not on a fixed timer)."
    )


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
    lines.append(check_run_tab_refresh_hint_bullet())
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
        if view.force_pass_active:
            lines.insert(
                -1,
                "- force pass is currently active, merge unblock with no cloud run job execution",
            )
        lines.append(check_run_tab_refresh_hint_bullet())
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
    lines.append(check_run_tab_refresh_hint_bullet())
    if view.failed_bmts:
        lines.extend(["", "Failed BMTs:"])
        lines.extend(f"- `{bmt}`: {reason}" for bmt, reason in view.failed_bmts)
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
    leg_done: bool,
    score_extra: dict[str, Any] | None = None,
    score_direction_label: str = "",
) -> str:
    """Format the Avg. column for GitHub Checks (avoid misleading 0.00 when score is unavailable)."""
    if score_extra and score_extra.get("unavailable"):
        return MISSING_SCORE
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


def _progress_table_markdown(view: CheckProgressView) -> str:
    lines = [
        "| Project | BMT | Status | Avg. | Tests | Duration |",
        "|---------|-----|--------|------|-------|----------|",
    ]
    for row in view.bmts:
        leg_done = row.status in (BmtLegStatus.PASS.value, BmtLegStatus.FAIL.value)
        score_extra = row.score_extra if row.has_completed_summary else None
        score_s = _score_cell_for_check(
            aggregate_score=row.aggregate_score,
            leg_done=leg_done,
            score_extra=score_extra,
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
                    _format_duration(row.duration_sec),
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


_RESERVED_CASE_KEYS = frozenset({"case_id", "status", "error", "log_name"})


def _cases_ok_detail_from_metrics_dict(metrics: dict[str, Any]) -> str:
    cases_ok = metrics.get("cases_ok")
    case_count = metrics.get("case_count")
    if cases_ok is None or case_count is None:
        return ""
    return f"{cases_ok}/{case_count} ok"


def case_outcomes_from_metrics(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized ``metrics.case_outcomes`` rows for Checks and digests."""
    raw = metrics.get("case_outcomes")
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, dict)]


def _primary_metric_header_and_key(score_extra: dict[str, Any]) -> tuple[str, str]:
    sp = score_extra.get("scoring_policy")
    if isinstance(sp, dict):
        pm = sp.get("primary_metric")
        key = str(pm).strip() if isinstance(pm, str) else ""
        if key:
            hints = sp.get("reporting_hints")
            if isinstance(hints, dict):
                msl = hints.get("metric_short_label")
                if isinstance(msl, str) and msl.strip():
                    return msl.strip(), key
            return key, key
    return ("Score", "")


def _first_numeric_metric_key(case: dict[str, Any]) -> str:
    for k, v in case.items():
        if k in _RESERVED_CASE_KEYS:
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return str(k)
    return ""


def _format_metric_cell(v: object) -> str:
    if isinstance(v, bool):
        return _md_table_cell(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s or "0"
    return MISSING_SCORE if v is None else _md_table_cell(v)


def _case_metric_cell(case: dict[str, Any], metric_key: str) -> str:
    if metric_key:
        return _format_metric_cell(case.get(metric_key))
    fk = _first_numeric_metric_key(case)
    if not fk:
        return MISSING_SCORE
    return _format_metric_cell(case.get(fk))


def _case_status_display(status: object) -> str:
    s = str(status).strip().lower()
    if s == _CASE_OUTCOME_STATUS_PASSED:
        return "pass"
    if s in ("failed", "fail", "failure", "error", "timeout"):
        return "fail"
    return _md_table_cell(status)


def _collapsible_leg_file_table(
    *,
    project: str,
    bmt: str,
    cases_detail: str,
    aggregate_score: float | None,
    score_extra: dict[str, Any],
    score_direction_label: str,
    case_outcomes: list[dict[str, Any]],
    leg_done: bool,
) -> str:
    if not case_outcomes:
        return ""
    header_label, metric_key = _primary_metric_header_and_key(score_extra)
    if not metric_key and case_outcomes:
        metric_key = _first_numeric_metric_key(case_outcomes[0])
        if metric_key and header_label == "Score":
            header_label = metric_key
    avg_s = _score_cell_for_check(
        aggregate_score=aggregate_score,
        leg_done=leg_done,
        score_extra=score_extra,
        score_direction_label=score_direction_label,
    )
    parts = [f"{project}/{bmt}"]
    if cases_detail.strip():
        parts.append(cases_detail.strip())
    parts.append(f"avg {avg_s}")
    dir_lab = (score_direction_label or "").strip()
    if dir_lab:
        parts.append(f"({dir_lab})")
    summary_plain = " · ".join(parts)
    lines = [
        "<details>",
        f"<summary>{html.escape(summary_plain)}</summary>",
        "",
        f"| File | Status | {header_label} | Error | Log |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in case_outcomes:
        cid = _md_table_cell(c.get("case_id", ""))
        st = _case_status_display(c.get("status"))
        metric_col = _case_metric_cell(c, metric_key)
        err = _md_table_cell(c.get("error", ""))
        logn = _md_table_cell(c.get("log_name", ""))
        lines.append(f"| {cid} | {st} | {metric_col} | {err} | {logn} |")
    lines.append("</details>")
    return "\n".join(lines)


def per_leg_file_scores_collapsible_markdown(rows: list[FinalBmtRow]) -> str:
    """One ``<details>`` block per leg with a Markdown table of per-file scores."""
    blocks: list[str] = []
    for row in rows:
        block = _collapsible_leg_file_table(
            project=row.project,
            bmt=row.bmt,
            cases_detail=row.cases_detail,
            aggregate_score=row.aggregate_score,
            score_extra=row.score_extra,
            score_direction_label=row.score_direction_label,
            case_outcomes=row.case_outcomes,
            leg_done=True,
        )
        if block:
            blocks.append(block)
    return "\n\n".join(blocks).strip()


def per_leg_file_scores_collapsible_markdown_progress(view: CheckProgressView) -> str:
    """Per-leg ``<details>`` for legs that already finished (progress check updates)."""
    blocks: list[str] = []
    for row in view.bmts:
        if not row.has_completed_summary:
            continue
        leg_done = row.status in (BmtLegStatus.PASS.value, BmtLegStatus.FAIL.value)
        block = _collapsible_leg_file_table(
            project=row.project,
            bmt=row.bmt,
            cases_detail=row.cases_detail,
            aggregate_score=row.aggregate_score,
            score_extra=row.score_extra,
            score_direction_label=row.score_direction_label,
            case_outcomes=row.case_outcomes,
            leg_done=leg_done,
        )
        if block:
            blocks.append(block)
    return "\n\n".join(blocks).strip()


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
    summary_lines.append("- Expand **Per-file scores** for each finished leg to see every test file.")
    table = _progress_table_markdown(view)
    legs_md = per_leg_file_scores_collapsible_markdown_progress(view)
    text = f"{table}\n\n### Per-file scores\n\n{legs_md}" if legs_md.strip() else table
    return {
        "title": f"BMT Running: {view.completed_count}/{view.total_count} complete",
        "summary": "\n".join(summary_lines),
        "text": text,
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
            out.append(
                {
                    "path": path,
                    "start_line": 1,
                    "end_line": 1,
                    "annotation_level": "failure",
                    "message": msg or "(no error message)",
                }
            )
    return out


def multi_leg_score_scope_markdown(row_count: int) -> str:
    """Fallback scope line; prefer :func:`run_context_blurb_markdown` when ``FinalBmtRow`` data exists."""
    if row_count <= 1:
        return ""
    return "*Different BMT rows may use different metrics and directions; raw **Avg.** values are not automatically comparable.*"


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
    case_outcomes = case_outcomes_from_metrics(metrics)
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
        cases_detail=_cases_ok_detail_from_metrics_dict(metrics),
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
    return summary + "\n\n" + "\n".join(tail)


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
    blurb_md = run_context_blurb_markdown(view.bmts)
    text_parts: list[str] = []
    if blurb_md:
        text_parts.append(blurb_md.rstrip())
    else:
        scope_md = multi_leg_score_scope_markdown(len(view.bmts))
        if scope_md:
            text_parts.append(scope_md.rstrip())
    text_parts.append(_final_check_table_markdown(view))
    file_scores_md = per_leg_file_scores_collapsible_markdown(view.bmts)
    if file_scores_md:
        text_parts.extend(["", "### Per-file scores", "", file_scores_md])
    annotations = github_check_annotations_from_final_rows(view.bmts)
    out: dict[str, Any] = {
        "title": f"BMT Complete: {CHECK_TITLE_PASS if is_success else CHECK_TITLE_FAIL}",
        "summary": "\n".join(lines),
        "text": "\n\n".join(text_parts),
    }
    if annotations:
        out["annotations"] = annotations
    return out  # type: ignore[return-value]


def _final_status_label(status: str) -> str:
    return "PASS" if leg_status_is_pass(status) else "FAIL"


def _format_eta(seconds: int | None) -> str:
    return _format_duration(seconds) if seconds is not None else _ETA_UNKNOWN


def _format_duration(seconds: int | None) -> str:
    return format_duration_seconds(seconds)

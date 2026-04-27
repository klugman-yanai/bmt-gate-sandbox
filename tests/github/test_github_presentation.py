from __future__ import annotations

import pytest

from runtime.config.bmt_domain_status import BmtLegStatus
from runtime.github.presentation import (
    CheckFinalView,
    CheckProgressView,
    FinalBmtRow,
    FinalCommentView,
    LiveLinks,
    ProgressBmtRow,
    StartedCommentView,
    check_run_tab_refresh_hint_bullet,
    multi_leg_score_scope_markdown,
    render_final_check_output,
    render_final_pr_comment,
    render_progress_check_output,
    render_started_pr_comment,
    run_context_blurb_markdown,
)

pytestmark = pytest.mark.unit


def test_render_started_pr_comment_is_short_and_human_readable() -> None:
    rendered = render_started_pr_comment(
        StartedCommentView(
            head_sha="0123456789abcdef",
            links=LiveLinks(workflow_execution_url="https://example.test/workflows/123"),
        )
    )

    assert "<!-- bmt-gate-comment -->" in rendered
    assert "## BMT Started" in rendered
    assert "BMTs are running for `0123456`." in rendered
    assert (
        'Live runtime: <a href="https://example.test/workflows/123" target="_blank" rel="noopener noreferrer">BMT Cloud Job (GCP Console)</a>'
        in rendered
    )
    assert "Detailed progress: see the **BMT Gate** check" in rendered
    assert "**Checks tab:**" in rendered
    assert "milestone" in rendered.lower()
    assert "<details>" not in rendered
    assert "| Project |" not in rendered


def test_check_run_tab_refresh_hint_respects_interval_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.config import constants as c

    monkeypatch.setenv(c.ENV_BMT_CHECK_RUN_DETAIL_PUBLISH_INTERVAL_SEC, "45")
    hint = check_run_tab_refresh_hint_bullet()
    assert "45s" in hint
    assert "at most every" in hint


def test_render_final_success_pr_comment_stays_brief() -> None:
    rendered = render_final_pr_comment(
        FinalCommentView(
            head_sha="fedcba9876543210",
            state="success",
            links=LiveLinks(workflow_execution_url="https://example.test/workflows/123"),
        )
    )

    assert "## BMT Passed" in rendered
    assert "BMTs passed for `fedcba9`." in rendered
    assert "- Status: `success`" in rendered
    assert (
        '- Live runtime: <a href="https://example.test/workflows/123" target="_blank" rel="noopener noreferrer">BMT Cloud Job (GCP Console)</a>'
        in rendered
    )
    assert "- Full details: see the **BMT Gate** check" in rendered
    assert "**Checks tab:**" in rendered
    assert "Failed BMTs:" not in rendered
    assert "| Project |" not in rendered


def test_render_final_failure_pr_comment_lists_failed_bmts_without_table() -> None:
    rendered = render_final_pr_comment(
        FinalCommentView(
            head_sha="fedcba9876543210",
            state="failure",
            links=LiveLinks(
                workflow_execution_url="https://example.test/workflows/123",
                log_dump_url="https://example.test/log-dump",
            ),
            failed_bmts=[("false_rejects", "score dropped below baseline"), ("false_alarms", "the runner timed out")],
        )
    )

    assert "## BMT Failed" in rendered
    assert "One or more BMTs failed for `fedcba9`." in rendered
    assert "- Failure log dump: [3-day link](https://example.test/log-dump)" in rendered
    assert "- Full details: see the **BMT Gate** check" in rendered
    assert "**Checks tab:**" in rendered
    assert "Failed BMTs:" in rendered
    assert "- `false_rejects`: score dropped below baseline" in rendered
    assert "- `false_alarms`: the runner timed out" in rendered
    assert "| Project |" not in rendered


def test_render_final_success_pr_comment_mentions_force_pass_when_active() -> None:
    rendered = render_final_pr_comment(
        FinalCommentView(
            head_sha="fedcba9876543210",
            state="success",
            links=LiveLinks(workflow_execution_url="https://example.test/workflows/123"),
            force_pass_active=True,
        )
    )
    assert "force pass is currently active, merge unblock with no cloud run job execution" in rendered


def test_render_progress_check_output_shows_bmt_table_and_progress() -> None:
    output = render_progress_check_output(
        CheckProgressView(
            completed_count=2,
            total_count=5,
            elapsed_sec=125,
            eta_sec=300,
            links=LiveLinks(workflow_execution_url="https://example.test/workflows/123"),
            bmts=[
                ProgressBmtRow(
                    project="sk",
                    bmt="false_rejects",
                    status="pass",
                    duration_sec=61,
                    has_completed_summary=True,
                    aggregate_score=12.34,
                ),
                ProgressBmtRow(project="sk", bmt="false_alarms", status="running", duration_sec=None),
            ],
        )
    )

    assert output["title"] == "BMT Running: 2/5 complete"
    assert "- Progress: `2/5` complete" in output["summary"]
    assert "- Elapsed: `2m 5s`" in output["summary"]
    assert "- ETA: `5m 0s`" in output["summary"]
    assert "| Project |" not in output["summary"]
    assert "per-file scores" in output["summary"].lower()
    text = output.get("text") or ""
    assert "| Project | BMT | Status | Avg. | Tests | Duration |" in text
    assert "| sk | false_rejects | Complete | 12.34 | — | 1m 1s |" in text
    assert "| sk | false_alarms | Running | — | — | — |" in text
    assert "### Per-file scores" not in text


def test_render_progress_check_output_includes_per_file_when_leg_finished() -> None:
    output = render_progress_check_output(
        CheckProgressView(
            completed_count=1,
            total_count=1,
            elapsed_sec=1,
            eta_sec=None,
            links=LiveLinks(workflow_execution_url=""),
            bmts=[
                ProgressBmtRow(
                    project="sk",
                    bmt="false_rejects",
                    status=BmtLegStatus.PASS.value,
                    has_completed_summary=True,
                    aggregate_score=1.0,
                    cases_detail="1/1 ok",
                    score_direction_label="lower better",
                    score_extra={"scoring_policy": {"primary_metric": "namuh_count"}},
                    case_outcomes=[
                        {"case_id": "f.wav", "status": "ok", "namuh_count": 1.0, "error": "", "log_name": "f.log"},
                    ],
                ),
            ],
        )
    )
    text = output.get("text") or ""
    assert "### Per-file scores" in text
    assert "<details>" in text
    assert "f.wav" in text


def test_render_final_check_output_includes_score_scope_when_multiple_legs() -> None:
    output = render_final_check_output(
        CheckFinalView(
            state="success",
            links=LiveLinks(workflow_execution_url="https://example.test/wf"),
            bmts=[
                FinalBmtRow(
                    project="sk",
                    bmt="false_rejects",
                    status="pass",
                    aggregate_score=10.0,
                    reason_code="bootstrap_without_baseline",
                    duration_sec=1,
                ),
                FinalBmtRow(
                    project="sk",
                    bmt="false_alarms",
                    status="pass",
                    aggregate_score=2.0,
                    reason_code="bootstrap_without_baseline",
                    duration_sec=2,
                ),
            ],
        )
    )
    text_out = output.get("text") or ""
    assert "Each BMT row stands alone" in text_out
    assert "separate" in text_out.lower()


def test_multi_leg_score_scope_markdown_empty_for_single() -> None:
    assert multi_leg_score_scope_markdown(1) == ""


def test_run_context_blurb_includes_hints_from_scoring_policy() -> None:
    md = run_context_blurb_markdown(
        [
            FinalBmtRow(
                project="sk",
                bmt="false_alarms",
                status="pass",
                aggregate_score=0.0,
                reason_code="score_lte_last",
                score_extra={
                    "scoring_policy": {
                        "score_direction_hint": "lower_better",
                        "primary_metric": "namuh_count",
                        "reporting_hints": {
                            "success_in_words": "Zero false alarms is ideal here.",
                            "metric_short_label": "false alarms per file (avg.)",
                        },
                    }
                },
            ),
            FinalBmtRow(
                project="sk",
                bmt="false_rejects",
                status="pass",
                aggregate_score=99.0,
                reason_code="score_gte_last",
                score_extra={
                    "scoring_policy": {
                        "score_direction_hint": "higher_better",
                        "primary_metric": "namuh_count",
                        "reporting_hints": {
                            "success_in_words": "Higher keyword hits are better.",
                            "metric_short_label": "hits per file (avg.)",
                        },
                    }
                },
            ),
        ]
    )
    assert "Each BMT row stands alone" in md
    assert "`sk` / `false_alarms`" in md
    assert "Zero false alarms is ideal here." in md
    assert "`sk` / `false_rejects`" in md
    assert "Higher keyword hits are better." in md


def test_run_context_blurb_prefers_check_run_copy_success_text() -> None:
    md = run_context_blurb_markdown(
        [
            FinalBmtRow(
                project="kt",
                bmt="wakeword_gate",
                status="pass",
                aggregate_score=7.0,
                reason_code="score_gte_last",
                score_extra={
                    "check_run_copy": {
                        "success_in_words": "Treat this as a wakeword precision score for KT.",
                        "metric_label": "precision points (avg.)",
                    }
                },
            )
        ]
    )
    assert "Treat this as a wakeword precision score for KT." in md
    assert "precision points (avg.)" in md


def test_render_final_failure_check_output_owns_the_detailed_table() -> None:
    output = render_final_check_output(
        CheckFinalView(
            state="failure",
            links=LiveLinks(
                workflow_execution_url="https://example.test/workflows/123",
                log_dump_url="https://example.test/log-dump",
            ),
            bmts=[
                FinalBmtRow(
                    project="sk",
                    bmt="false_rejects",
                    status="fail",
                    aggregate_score=41.25,
                    reason_code="score_below_last",
                    duration_sec=65,
                    cases_detail="22/24 passed",
                ),
                FinalBmtRow(
                    project="sk",
                    bmt="false_alarms",
                    status="pass",
                    aggregate_score=56.8,
                    reason_code="score_gte_last",
                    duration_sec=59,
                    cases_detail="30/30 passed",
                ),
            ],
        )
    )

    assert output["title"] == "BMT Complete: FAIL"
    assert "- Result: `failure`" in output["summary"]
    assert "- Log dump (expires in 3 days): [open](https://example.test/log-dump)" in output["summary"]
    assert "| Project |" not in output["summary"]
    assert "### Failure summary" in output["summary"]
    assert "- `false_rejects`: score dropped below baseline" in output["summary"]
    text = output.get("text") or ""
    assert "| Project | BMT | Status | Avg. | Tests | Reason | Duration |" in text
    assert "| sk | false_rejects | FAIL | 41.25 | 22/24 passed | score dropped below baseline | 1m 5s |" in text
    assert "| sk | false_alarms | PASS | 56.80 | 30/30 passed | score met or exceeded baseline | 59s |" in text


def test_render_final_check_output_uses_custom_reason_text_when_provided() -> None:
    output = render_final_check_output(
        CheckFinalView(
            state="failure",
            links=LiveLinks(workflow_execution_url="https://example.test/wf"),
            bmts=[
                FinalBmtRow(
                    project="kt",
                    bmt="wakeword_gate",
                    status="fail",
                    aggregate_score=3.2,
                    reason_code="score_below_last",
                    score_extra={"check_run_copy": {"reason_text": "custom KT policy threshold was missed"}},
                ),
            ],
        )
    )
    summary = output.get("summary") or ""
    text = output.get("text") or ""
    assert "custom KT policy threshold was missed" in summary
    assert "| kt | wakeword_gate | FAIL | 3.20 | — | custom KT policy threshold was missed | — |" in text


def test_render_final_check_output_unavailable_score_not_shown_as_numeric() -> None:
    """Coordinator synthetic summary (missing file) marks score unavailable, not 0.00."""
    output = render_final_check_output(
        CheckFinalView(
            state="failure",
            links=LiveLinks(workflow_execution_url="https://example.test/wf"),
            bmts=[
                FinalBmtRow(
                    project="sk",
                    bmt="false_alarms",
                    status="fail",
                    aggregate_score=0.0,
                    reason_code="runner_failures",
                    duration_sec=None,
                    score_extra={"unavailable": True},
                ),
            ],
        )
    )
    final_text = output.get("text") or ""
    assert "| sk | false_alarms | FAIL | — | — |" in final_text
    assert "| sk | false_alarms | FAIL | 0.00 |" not in final_text


def test_render_final_check_output_pass_with_zero_score_shows_numeric() -> None:
    """Completed pass legs show 0.00 when aggregate score is zero (real runner/plugin path)."""
    output = render_final_check_output(
        CheckFinalView(
            state="success",
            links=LiveLinks(workflow_execution_url="https://example.test/wf"),
            bmts=[
                FinalBmtRow(
                    project="sk",
                    bmt="false_rejects",
                    status="pass",
                    aggregate_score=0.0,
                    reason_code="bootstrap_without_baseline",
                    duration_sec=1,
                    execution_mode_used="plugin",
                ),
            ],
        )
    )
    assert "| sk | false_rejects | PASS | 0.00 | — |" in (output.get("text") or "")


def test_human_reason_runner_case_failures() -> None:
    from runtime.github.presentation import human_reason

    assert human_reason("runner_case_failures") == "runner crashed on one or more test files"


def test_human_reason_no_dataset_cases() -> None:
    from runtime.github.presentation import human_reason

    assert "no test cases" in human_reason("no_dataset_cases")


def test_human_reason_plugin_execute_failed() -> None:
    from runtime.github.presentation import human_reason

    assert "execute" in human_reason("plugin_execute_failed").lower()


def test_render_final_check_output_per_file_scores_collapsible_and_annotations() -> None:
    output = render_final_check_output(
        CheckFinalView(
            state="failure",
            links=LiveLinks(workflow_execution_url="https://example.test/wf"),
            bmts=[
                FinalBmtRow(
                    project="sk",
                    bmt="false_alarms",
                    status="fail",
                    aggregate_score=2.0,
                    reason_code="runner_case_failures",
                    duration_sec=10,
                    cases_detail="5/6 ok",
                    score_extra={
                        "scoring_policy": {
                            "primary_metric": "namuh_count",
                            "score_direction_hint": "lower_better",
                        },
                        "check_run_copy": {"metric_label": "false alarms per file"},
                    },
                    score_direction_label="lower better",
                    case_outcomes=[
                        {
                            "case_id": "bad.wav",
                            "status": "failed",
                            "namuh_count": 0.0,
                            "error": "runner_exit_139",
                            "log_name": "bad.wav.log",
                        },
                    ],
                ),
            ],
        )
    )
    text_body = output.get("text") or ""
    assert "### Per-file scores" in text_body
    assert "<details>" in text_body
    assert "</details>" in text_body
    assert "bad.wav" in text_body
    assert "runner_exit_139" in text_body
    assert "2.00 ↓" in text_body
    assert "false alarms per file" in text_body
    assert "### Per-case failures" not in text_body
    assert "annotations" in output
    assert output["annotations"][0]["path"].startswith("bmt/sk/false_alarms/")
    assert output["annotations"][0]["annotation_level"] == "failure"


def test_render_final_check_output_per_file_scores_two_files() -> None:
    output = render_final_check_output(
        CheckFinalView(
            state="success",
            links=LiveLinks(workflow_execution_url="https://example.test/wf"),
            bmts=[
                FinalBmtRow(
                    project="sk",
                    bmt="false_rejects",
                    status="pass",
                    aggregate_score=1.5,
                    reason_code="score_lte_last",
                    duration_sec=3,
                    cases_detail="2/2 ok",
                    score_extra={"scoring_policy": {"primary_metric": "namuh_count"}},
                    score_direction_label="lower better",
                    case_outcomes=[
                        {"case_id": "a.wav", "status": "ok", "namuh_count": 1.0, "error": "", "log_name": "a.log"},
                        {"case_id": "b.wav", "status": "ok", "namuh_count": 2.0, "error": "", "log_name": "b.log"},
                    ],
                ),
            ],
        )
    )
    text_body = output.get("text") or ""
    assert text_body.count("<details>") == 1
    assert "a.wav" in text_body and "b.wav" in text_body


def test_github_check_annotations_cap_at_50() -> None:
    from runtime.github.presentation import (
        MAX_GITHUB_CHECK_ANNOTATIONS,
        github_check_annotations_from_final_rows,
    )

    many = [
        {
            "case_id": f"c{i}.wav",
            "status": "failed",
            "namuh_count": 0.0,
            "error": "e",
            "log_name": "",
        }
        for i in range(60)
    ]
    row = FinalBmtRow(
        project="sk",
        bmt="x",
        status="fail",
        aggregate_score=0.0,
        reason_code="runner_case_failures",
        case_outcomes=many,
    )
    ann = github_check_annotations_from_final_rows([row])
    assert len(ann) == MAX_GITHUB_CHECK_ANNOTATIONS


def test_human_reason_unknown_code_is_explicit() -> None:
    from runtime.github.presentation import human_reason

    assert human_reason("totally_unknown_reason") == "unmapped reason code: `totally_unknown_reason`"
    assert human_reason("") == "empty reason code"

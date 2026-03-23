from __future__ import annotations

import pytest

from gcp.image.github.presentation import (
    CheckFinalView,
    CheckProgressView,
    FinalBmtRow,
    FinalCommentView,
    LiveLinks,
    ProgressBmtRow,
    StartedCommentView,
    render_final_check_output,
    render_final_pr_comment,
    render_progress_check_output,
    render_started_pr_comment,
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
    assert "<details>" not in rendered
    assert "| Project |" not in rendered


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
    assert "Failed BMTs:" in rendered
    assert "- `false_rejects`: score dropped below baseline" in rendered
    assert "- `false_alarms`: the runner timed out" in rendered
    assert "| Project |" not in rendered


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
    text = output["text"]
    assert "| Project | BMT | Status | Score | Cases | Duration |" in text
    assert "| sk | false_rejects | Complete | 12.34 | — | 1m 1s |" in text
    assert "| sk | false_alarms | Running | — | — | — |" in text


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
                    cases_detail="22/24 ok",
                ),
                FinalBmtRow(
                    project="sk",
                    bmt="false_alarms",
                    status="pass",
                    aggregate_score=56.8,
                    reason_code="score_gte_last",
                    duration_sec=59,
                    cases_detail="30/30 ok",
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
    text = output["text"]
    assert "| Project | BMT | Status | Score | Cases | Reason | Duration |" in text
    assert "| sk | false_rejects | FAIL | 41.25 | 22/24 ok | score dropped below baseline | 1m 5s |" in text
    assert "| sk | false_alarms | PASS | 56.80 | 30/30 ok | score met or exceeded baseline | 59s |" in text


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
    assert "| sk | false_alarms | FAIL | — | — |" in output["text"]
    assert "| sk | false_alarms | FAIL | 0.00 |" not in output["text"]


def test_render_final_check_output_mock_runner_shows_placeholder_not_zero() -> None:
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
                    execution_mode_used="mock",
                ),
            ],
        )
    )
    assert "| sk | false_rejects | PASS | — (mock) | — |" in output["text"]


def test_human_reason_runner_case_failures() -> None:
    from gcp.image.github.presentation import human_reason

    assert human_reason("runner_case_failures") == "runner crashed on one or more test files"


def test_human_reason_no_dataset_cases() -> None:
    from gcp.image.github.presentation import human_reason

    assert "no test cases" in human_reason("no_dataset_cases")


def test_human_reason_plugin_execute_failed() -> None:
    from gcp.image.github.presentation import human_reason

    assert "execute" in human_reason("plugin_execute_failed").lower()


def test_human_reason_unknown_code_is_explicit() -> None:
    from gcp.image.github.presentation import human_reason

    assert human_reason("totally_unknown_reason") == "unmapped reason code: `totally_unknown_reason`"
    assert human_reason("") == "empty reason code"

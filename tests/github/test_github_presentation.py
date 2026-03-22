from __future__ import annotations

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
    assert 'Live runtime: <a href="https://example.test/workflows/123" target="_blank" rel="noopener noreferrer">BMT Cloud Job (GCP Console)</a>' in rendered
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
    assert '- Live runtime: <a href="https://example.test/workflows/123" target="_blank" rel="noopener noreferrer">BMT Cloud Job (GCP Console)</a>' in rendered
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
                ProgressBmtRow(project="sk", bmt="false_rejects", status="pass", duration_sec=61),
                ProgressBmtRow(project="sk", bmt="false_alarms", status="running", duration_sec=None),
            ],
        )
    )

    assert output["title"] == "BMT Running: 2/5 complete"
    assert "- Progress: `2/5` complete" in output["summary"]
    assert "- Elapsed: `2m 5s`" in output["summary"]
    assert "- ETA: `5m 0s`" in output["summary"]
    assert "| Project | BMT | Status | Duration |" in output["summary"]
    assert "| sk | false_rejects | Complete | 1m 1s |" in output["summary"]
    assert "| sk | false_alarms | Running | — |" in output["summary"]


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
                ),
                FinalBmtRow(
                    project="sk",
                    bmt="false_alarms",
                    status="pass",
                    aggregate_score=56.8,
                    reason_code="score_gte_last",
                    duration_sec=59,
                ),
            ],
        )
    )

    assert output["title"] == "BMT Complete: FAIL"
    assert "- Result: `failure`" in output["summary"]
    assert "- Log dump (expires in 3 days): [open](https://example.test/log-dump)" in output["summary"]
    assert "| Project | BMT | Status | Score | Reason | Duration |" in output["summary"]
    assert "| sk | false_rejects | FAIL | 41.25 | score dropped below baseline | 1m 5s |" in output["summary"]
    assert "| sk | false_alarms | PASS | 56.80 | score met or exceeded baseline | 59s |" in output["summary"]
    assert "### Failure summary" in output["summary"]
    assert "- `false_rejects`: score dropped below baseline" in output["summary"]

from __future__ import annotations

from pathlib import Path

from ci.models import AggregateRow, LegOutcome


def write_github_output(github_output: str | None, key: str, value: str) -> None:
    """Append key=value to GITHUB_OUTPUT file (silently no-ops if path is None)."""
    if not github_output:
        return
    with Path(github_output).open("a", encoding="utf-8") as fh:
        _ = fh.write(f"{key}={value}\n")


def emit_leg_annotation(outcome: LegOutcome) -> None:
    """Emit a GitHub Actions notice/warning/error annotation for a leg outcome."""
    score_text = "n/a" if outcome.aggregate_score is None else str(outcome.aggregate_score)
    message = (
        f"{outcome.project}.{outcome.bmt_id} "
        f"runner={outcome.runner.name}@{outcome.runner.build_id} "
        f"score={score_text} status={outcome.status} reason={outcome.reason_code}"
    )
    if outcome.status == "pass":
        print(f"::notice::{message}")
    elif outcome.status == "warning":
        print(f"::warning::{message}")
    else:
        print(f"::error::{message}")


def write_aggregate_step_summary(
    summary_path: str | None,
    decision: str,
    rows: list[AggregateRow],
    counts: dict[str, int],
    blocked_legs: list[str],
    blocked_reasons: list[str],
) -> None:
    """Write the aggregate matrix outcome table to GITHUB_STEP_SUMMARY."""
    if not summary_path:
        return

    lines = [
        "## BMT Matrix Outcomes",
        "",
        f"Final decision: **{decision}**",
        "",
        "| Project.BMT | Runner@Build | Score | Status | Reason |",
        "|---|---|---:|---|---|",
    ]

    if rows:
        for row in sorted(rows, key=lambda r: (r.project, r.bmt_id)):
            score_text = "" if row.score is None else str(row.score)
            lines.append(
                f"| {row.project}.{row.bmt_id} | {row.runner_name}@{row.runner_build}"
                f" | {score_text} | {row.status} | {row.reason} |"
            )
    else:
        lines.append("| - | - |  | timeout | no_outcomes_found |")

    lines.extend(
        [
            "",
            f"Pass: {counts['pass']}",
            f"Warnings: {counts['warning']}",
            f"Fails: {counts['fail']}",
            f"Timeouts: {counts['timeout']}",
            f"Blockers: {', '.join(sorted(blocked_legs)) if blocked_legs else 'none'}",
            f"Blocker reasons: {', '.join(sorted(blocked_reasons)) if blocked_reasons else 'none'}",
        ]
    )

    with Path(summary_path).open("a", encoding="utf-8") as fh:
        _ = fh.write("\n".join(lines) + "\n")

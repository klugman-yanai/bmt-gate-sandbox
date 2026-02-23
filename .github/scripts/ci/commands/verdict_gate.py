from __future__ import annotations

import sys

import click

from ci import models


@click.command("gate")
@click.option("--decision", required=True)
@click.option("--pass-count", required=True)
@click.option("--warning-count", required=True)
@click.option("--fail-count", required=True)
@click.option("--timeout-count", required=True)
@click.option("--blocked-legs", default="")
@click.option("--blocked-reasons", default="")
def command(
    decision: str,
    pass_count: str,
    warning_count: str,
    fail_count: str,
    timeout_count: str,
    blocked_legs: str,
    blocked_reasons: str,
) -> None:
    """Evaluate final merge gate decision."""
    legs_str = blocked_legs.strip() or "none"
    reasons_str = blocked_reasons.strip() or "none"

    print(f"Final decision: {decision}")
    print(f"Counts -> pass={pass_count} warning={warning_count} fail={fail_count} timeout={timeout_count}")
    print(f"Blocked legs: {legs_str}")
    print(f"Blocked reasons: {reasons_str}")

    if decision == models.DECISION_ACCEPTED:
        print("::notice::BMT accepted")
    elif decision == models.DECISION_ACCEPTED_WITH_WARNINGS:
        print("::warning::BMT accepted with warnings")
    elif decision == models.DECISION_REJECTED:
        print(f"::error::BMT rejected due to failing matrix legs: {legs_str}")
    elif decision == models.DECISION_TIMEOUT:
        print(f"::error::BMT rejected due to timeout legs: {legs_str}")
    else:
        print(f"::error::Unknown final decision: {decision}", file=sys.stderr)
        sys.exit(1)

    sys.exit(models.decision_exit(decision))

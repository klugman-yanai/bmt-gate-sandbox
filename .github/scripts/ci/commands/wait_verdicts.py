from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from ci import config, models
from ci.adapters import gcloud_cli
from ci.github_output import emit_leg_annotation, write_aggregate_step_summary, write_github_output
from ci.models import AggregateRow, CloudVerdict, LegOutcome, RunnerIdentity, TriggerLeg
from ci.repo_paths import DEFAULT_CONFIG_ROOT


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unknown_runner() -> RunnerIdentity:
    return RunnerIdentity(name=models.REASON_UNKNOWN, build_id=models.REASON_UNKNOWN, source_ref="")


def _build_outcome(
    leg: TriggerLeg,
    bucket: str,
    *,
    status: str,
    reason_code: str,
    verdict: dict[str, Any] | None = None,
    aggregate_score: float | None = None,
    runner: RunnerIdentity | None = None,
    collection_error: str | None = None,
) -> LegOutcome:
    return LegOutcome(
        project=leg.project,
        bmt_id=leg.bmt_id,
        run_id=leg.run_id,
        status=status,
        reason_code=reason_code,
        bucket=bucket,
        verdict_uri=leg.verdict_uri,
        verdict=verdict,
        aggregate_score=aggregate_score,
        runner=runner or _unknown_runner(),
        collection_error=collection_error,
        triggered_at=leg.triggered_at,
        collected_at=_now_iso(),
    )


def _parse_manifest(
    manifest_json: str,
    config_root: Path,
    bucket_root: str,
) -> list[TriggerLeg]:
    """Parse manifest legs; resolve results_prefix and verdict_uri from config when missing (pointer layout)."""
    data = json.loads(manifest_json)
    legs: list[TriggerLeg] = []
    for item in data.get("legs", []):
        project = str(item["project"])
        bmt_id = str(item["bmt_id"])
        run_id = str(item["run_id"])
        triggered_at = str(item["triggered_at"])
        trigger_uri = str(item.get("trigger_uri", ""))
        if item.get("results_prefix") and item.get("verdict_uri"):
            results_prefix = str(item["results_prefix"])
            verdict_uri = str(item["verdict_uri"])
        else:
            results_prefix = config.resolve_results_prefix(config_root, project, bmt_id)
            verdict_uri = models.snapshot_verdict_uri(bucket_root, results_prefix, run_id)
        legs.append(
            TriggerLeg(
                project=project,
                bmt_id=bmt_id,
                run_id=run_id,
                results_prefix=results_prefix,
                verdict_uri=verdict_uri,
                trigger_uri=trigger_uri,
                triggered_at=triggered_at,
            )
        )
    return legs


def _group_by_prefix(legs: list[TriggerLeg]) -> dict[str, list[TriggerLeg]]:
    """Group legs by results_prefix for batched GCS listing."""
    groups: dict[str, list[TriggerLeg]] = defaultdict(list)
    for leg in legs:
        groups[leg.results_prefix].append(leg)
    return dict(groups)


def _collect_verdict(leg: TriggerLeg, bucket: str) -> LegOutcome:
    """Download and validate a verdict for one leg."""
    verdict_payload, verdict_error = gcloud_cli.download_json(leg.verdict_uri)

    status = models.STATUS_FAIL
    reason_code = models.REASON_VERDICT_MISSING
    aggregate_score: float | None = None
    runner: RunnerIdentity | None = None
    verdict_dict: dict[str, Any] | None = None
    collection_error = verdict_error

    if verdict_payload is None:
        reason_code = models.REASON_VERDICT_MISSING
    else:
        verdict = CloudVerdict.from_payload(verdict_payload)
        verdict_dict = verdict.raw
        if verdict.run_id != leg.run_id:
            reason_code = models.REASON_VERDICT_RUN_ID_MISMATCH
            collection_error = f"expected_run_id={leg.run_id} actual_run_id={verdict.run_id or '<empty>'}"
        else:
            normalized_status = models.normalize_status(verdict.status)
            if normalized_status is None:
                reason_code = models.REASON_INVALID_STATUS
                collection_error = f"invalid_verdict_status={verdict.status!r}"
            else:
                status = normalized_status
                reason_code = verdict.reason_code or models.REASON_UNKNOWN
                aggregate_score = verdict.aggregate_score
                runner = verdict.runner

    return _build_outcome(
        leg,
        bucket,
        status=status,
        reason_code=reason_code,
        verdict=verdict_dict,
        aggregate_score=aggregate_score,
        runner=runner,
        collection_error=collection_error,
    )


def _current_pointer_latest(bucket_root: str, results_prefix: str) -> str | None:
    """Read current.json from GCS; return pointer['latest'] run_id or None if missing/invalid."""
    uri = models.current_pointer_uri(bucket_root, results_prefix)
    payload, _ = gcloud_cli.download_json(uri)
    if not payload or not isinstance(payload, dict):
        return None
    latest = payload.get("latest")
    return str(latest).strip() if latest else None


def _poll_and_collect(
    pending: dict[str, TriggerLeg],
    prefix_groups: dict[str, list[TriggerLeg]],
    bucket_root: str,
    bucket: str,
    deadline: float,
    poll_interval_sec: int,
    total_legs: int,
) -> list[LegOutcome]:
    """Poll GCS for verdicts until all collected or deadline reached. Returns collected outcomes."""
    collected: list[LegOutcome] = []

    while pending and time.monotonic() < deadline:
        found_this_cycle = False

        for results_prefix, group_legs in prefix_groups.items():
            latest_run_id = _current_pointer_latest(bucket_root, results_prefix)
            for leg in group_legs:
                if leg.run_id not in pending:
                    continue
                if latest_run_id is None or latest_run_id != leg.run_id:
                    continue
                try:
                    outcome = _collect_verdict(leg, bucket)
                except Exception as exc:
                    outcome = _build_outcome(
                        leg,
                        bucket,
                        status=models.STATUS_FAIL,
                        reason_code=models.REASON_CI_DRIVER_EXCEPTION,
                        collection_error=str(exc),
                    )
                collected.append(outcome)
                del pending[leg.run_id]
                emit_leg_annotation(outcome)
                found_this_cycle = True

                score_text = "n/a" if outcome.aggregate_score is None else str(outcome.aggregate_score)
                print(
                    f"  collected {outcome.project}.{outcome.bmt_id} "
                    f"status={outcome.status} score={score_text} "
                    f"({len(collected)}/{total_legs})"
                )

        if not pending:
            break

        if not found_this_cycle:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(poll_interval_sec, remaining))

    # Timeout remaining legs
    for leg in pending.values():
        outcome = _build_outcome(
            leg,
            bucket,
            status=models.STATUS_TIMEOUT,
            reason_code=models.REASON_VERDICT_TIMEOUT,
        )
        collected.append(outcome)
        emit_leg_annotation(outcome)
        print(f"  timeout {leg.project}.{leg.bmt_id} run_id={leg.run_id}")

    return collected


def _aggregate(
    collected: list[LegOutcome],
) -> tuple[str, dict[str, int], list[AggregateRow], list[str], list[str]]:
    """Aggregate outcomes into decision, counts, rows, blocked_legs, blocked_reasons."""
    counts: dict[str, int] = {
        models.STATUS_PASS: 0,
        models.STATUS_WARNING: 0,
        models.STATUS_FAIL: 0,
        models.STATUS_TIMEOUT: 0,
    }
    rows: list[AggregateRow] = []
    blocked_legs: list[str] = []
    blocked_reasons: list[str] = []

    for outcome in collected:
        counts[outcome.status] += 1
        rows.append(
            AggregateRow(
                project=outcome.project,
                bmt_id=outcome.bmt_id,
                status=outcome.status,
                reason=outcome.reason_code,
                score=outcome.aggregate_score,
                runner_name=outcome.runner.name,
                runner_build=outcome.runner.build_id,
            )
        )
        if outcome.status in {models.STATUS_FAIL, models.STATUS_TIMEOUT}:
            blocked_legs.append(f"{outcome.project}.{outcome.bmt_id}")
            blocked_reasons.append(f"{outcome.project}.{outcome.bmt_id}({outcome.reason_code})")

    decision = models.decision_for_counts(
        pass_count=counts[models.STATUS_PASS],
        warning_count=counts[models.STATUS_WARNING],
        fail_count=counts[models.STATUS_FAIL],
        timeout_count=counts[models.STATUS_TIMEOUT],
    )

    return decision, counts, rows, blocked_legs, blocked_reasons


@click.command("wait")
@click.option("--manifest", required=True, help="JSON manifest from trigger step")
@click.option("--config-root", default=DEFAULT_CONFIG_ROOT, show_default=True, type=click.Path(path_type=Path))
@click.option("--bucket", required=True, envvar="GCS_BUCKET")
@click.option("--timeout-sec", required=True, type=int)
@click.option("--poll-interval-sec", default=30, type=int, show_default=True)
@click.option("--github-output", envvar="GITHUB_OUTPUT")
@click.option("--summary-path", envvar="GITHUB_STEP_SUMMARY")
def command(
    manifest: str,
    config_root: Path,
    bucket: str,
    timeout_sec: int,
    poll_interval_sec: int,
    github_output: str | None,
    summary_path: str | None,
) -> None:
    """Poll for verdict files (via current.json pointer), aggregate results, and output decision."""
    if not github_output:
        raise RuntimeError("GITHUB_OUTPUT is required")

    bucket_root = models.runtime_bucket_root_uri(bucket)
    legs = _parse_manifest(manifest, config_root, bucket_root)
    if not legs:
        raise RuntimeError("Empty manifest — nothing to wait for")

    pending: dict[str, TriggerLeg] = {leg.run_id: leg for leg in legs}
    prefix_groups = _group_by_prefix(legs)
    deadline = time.monotonic() + timeout_sec
    print(f"Waiting for {len(pending)} verdict(s), timeout={timeout_sec}s, poll={poll_interval_sec}s")

    collected = _poll_and_collect(pending, prefix_groups, bucket_root, bucket, deadline, poll_interval_sec, len(legs))

    decision, counts, rows, blocked_legs, blocked_reasons = _aggregate(collected)

    write_aggregate_step_summary(
        summary_path=summary_path,
        decision=decision,
        rows=rows,
        counts=counts,
        blocked_legs=blocked_legs,
        blocked_reasons=blocked_reasons,
    )

    print(f"\nDecision: {decision}")
    print(
        f"Counts: pass={counts['pass']} warning={counts['warning']} fail={counts['fail']} timeout={counts['timeout']}"
    )

    write_github_output(github_output, "decision", decision)
    write_github_output(github_output, "pass_count", str(counts[models.STATUS_PASS]))
    write_github_output(github_output, "warning_count", str(counts[models.STATUS_WARNING]))
    write_github_output(github_output, "fail_count", str(counts[models.STATUS_FAIL]))
    write_github_output(github_output, "timeout_count", str(counts[models.STATUS_TIMEOUT]))
    write_github_output(github_output, "blocked_legs", ",".join(sorted(blocked_legs)))
    write_github_output(github_output, "blocked_reasons", ",".join(sorted(blocked_reasons)))

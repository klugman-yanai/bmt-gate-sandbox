"""Poll GCS for BMT verdicts and aggregate results. Local/manual diagnostic tool — not used by workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from whenever import Instant

from tools.repo.paths import DEFAULT_CONFIG_ROOT
from tools.repo.results_prefix import resolve_results_prefix
from tools.shared.bucket_env import bucket_root_uri
from tools.shared.verdict import (
    current_pointer_uri,
    download_json as gcs_download_json,
    snapshot_verdict_uri,
)

# ── Status constants ────────────────────────────────────────────────────────────

STATUS_PASS = "pass"
STATUS_WARNING = "warning"
STATUS_FAIL = "fail"
STATUS_TIMEOUT = "timeout"
_VALID_STATUSES = frozenset({STATUS_PASS, STATUS_WARNING, STATUS_FAIL, STATUS_TIMEOUT})

REASON_VERDICT_MISSING = "verdict_missing"
REASON_VERDICT_RUN_ID_MISMATCH = "verdict_run_id_mismatch"
REASON_VERDICT_TIMEOUT = "verdict_timeout"
REASON_INVALID_STATUS = "invalid_status"
REASON_CI_DRIVER_EXCEPTION = "ci_driver_exception"
REASON_UNKNOWN = "unknown"


def _require_env(name: str) -> str:
    """Return env var value or raise RuntimeError if unset/empty."""
    val = (os.environ.get(name) or "").strip()
    if not val:
        raise RuntimeError(f"Required env var {name!r} is not set or empty")
    return val


def _write_github_output(github_output: str | None, key: str, value: str) -> None:
    """Append key=value to GITHUB_OUTPUT file (no-op if path is None)."""
    if not github_output:
        return
    with Path(github_output).open("a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def _normalize_status(raw: str) -> str | None:
    value = (raw or "").strip().lower()
    return value if value in _VALID_STATUSES else None


def _decision_for_counts(pass_count: int, warning_count: int, fail_count: int, timeout_count: int) -> str:
    if timeout_count > 0:
        return "timeout"
    if fail_count > 0:
        return "rejected"
    if warning_count > 0:
        return "accepted_with_warnings"
    if pass_count > 0:
        return "accepted"
    return "timeout"


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class RunnerIdentity:
    name: str
    build_id: str
    source_ref: str


@dataclass(slots=True)
class CloudVerdict:
    run_id: str
    project_id: str
    bmt_id: str
    status: str
    reason_code: str
    aggregate_score: float | None
    runner: RunnerIdentity
    gate: dict[str, Any] | None
    timestamps: dict[str, Any] | None
    artifacts: dict[str, Any] | None
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CloudVerdict:
        runner_payload = payload.get("runner", {})
        if not isinstance(runner_payload, dict):
            runner_payload = {}
        return cls(
            run_id=str(payload.get("run_id", "")),
            project_id=str(payload.get("project_id", "")),
            bmt_id=str(payload.get("bmt_id", "")),
            status=str(payload.get("status", "")),
            reason_code=str(payload.get("reason_code", "")),
            aggregate_score=(
                float(score)
                if (score := payload.get("aggregate_score")) is not None and isinstance(score, (int, float))
                else None
            ),
            runner=RunnerIdentity(
                name=str(runner_payload.get("name", "unknown")),
                build_id=str(runner_payload.get("build_id", "unknown")),
                source_ref=str(runner_payload.get("source_ref", "")),
            ),
            gate=payload.get("gate") if isinstance(payload.get("gate"), dict) else None,
            timestamps=(payload.get("timestamps") if isinstance(payload.get("timestamps"), dict) else None),
            artifacts=(payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else None),
            raw=payload,
        )


@dataclass(frozen=True, slots=True)
class TriggerLeg:
    project: str
    bmt_id: str
    run_id: str
    results_prefix: str
    verdict_uri: str
    trigger_uri: str
    triggered_at: str


@dataclass(slots=True)
class LegOutcome:
    project: str
    bmt_id: str
    run_id: str
    status: str
    reason_code: str
    bucket: str
    verdict_uri: str
    verdict: dict[str, Any] | None
    aggregate_score: float | None
    runner: RunnerIdentity
    collection_error: str | None
    triggered_at: str
    collected_at: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AggregateRow:
    project: str
    bmt_id: str
    status: str
    reason: str
    score: float | None
    runner_name: str
    runner_build: str


# ── Output helpers ─────────────────────────────────────────────────────────────


def _emit_leg_annotation(outcome: LegOutcome) -> None:
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


def _write_aggregate_step_summary(
    summary_path: str | None,
    decision: str,
    rows: list[AggregateRow],
    counts: dict[str, int],
    blocked_legs: list[str],
    blocked_reasons: list[str],
) -> None:
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


# ── Core logic ─────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return Instant.now().format_iso(unit="second")


def _unknown_runner() -> RunnerIdentity:
    return RunnerIdentity(name=REASON_UNKNOWN, build_id=REASON_UNKNOWN, source_ref="")


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


def _parse_manifest(manifest_json: str, config_root: Path, bucket_root: str) -> list[TriggerLeg]:
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
            results_prefix = resolve_results_prefix(config_root, project, bmt_id)
            verdict_uri = snapshot_verdict_uri(bucket_root, results_prefix, run_id)
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
    groups: dict[str, list[TriggerLeg]] = defaultdict(list)
    for leg in legs:
        groups[leg.results_prefix].append(leg)
    return dict(groups)


def _collect_verdict(leg: TriggerLeg, bucket: str) -> LegOutcome:
    verdict_payload, verdict_error = gcs_download_json(leg.verdict_uri)

    status = STATUS_FAIL
    reason_code = REASON_VERDICT_MISSING
    aggregate_score: float | None = None
    runner: RunnerIdentity | None = None
    verdict_dict: dict[str, Any] | None = None
    collection_error = verdict_error

    if verdict_payload is None:
        reason_code = REASON_VERDICT_MISSING
    else:
        verdict = CloudVerdict.from_payload(verdict_payload)
        verdict_dict = verdict.raw
        if verdict.run_id != leg.run_id:
            reason_code = REASON_VERDICT_RUN_ID_MISMATCH
            collection_error = f"expected_run_id={leg.run_id} actual_run_id={verdict.run_id or '<empty>'}"
        else:
            normalized_status = _normalize_status(verdict.status)
            if normalized_status is None:
                reason_code = REASON_INVALID_STATUS
                collection_error = f"invalid_verdict_status={verdict.status!r}"
            else:
                status = normalized_status
                reason_code = verdict.reason_code or REASON_UNKNOWN
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
    uri = current_pointer_uri(bucket_root, results_prefix)
    payload, _ = gcs_download_json(uri)
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
                        status=STATUS_FAIL,
                        reason_code=REASON_CI_DRIVER_EXCEPTION,
                        collection_error=str(exc),
                    )
                collected.append(outcome)
                del pending[leg.run_id]
                _emit_leg_annotation(outcome)
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

    for leg in pending.values():
        outcome = _build_outcome(leg, bucket, status=STATUS_TIMEOUT, reason_code=REASON_VERDICT_TIMEOUT)
        collected.append(outcome)
        _emit_leg_annotation(outcome)
        print(f"  timeout {leg.project}.{leg.bmt_id} run_id={leg.run_id}")

    return collected


def _aggregate(
    collected: list[LegOutcome],
) -> tuple[str, dict[str, int], list[AggregateRow], list[str], list[str]]:
    counts: dict[str, int] = {STATUS_PASS: 0, STATUS_WARNING: 0, STATUS_FAIL: 0, STATUS_TIMEOUT: 0}
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
        if outcome.status in {STATUS_FAIL, STATUS_TIMEOUT}:
            blocked_legs.append(f"{outcome.project}.{outcome.bmt_id}")
            blocked_reasons.append(f"{outcome.project}.{outcome.bmt_id}({outcome.reason_code})")

    decision = _decision_for_counts(
        pass_count=counts[STATUS_PASS],
        warning_count=counts[STATUS_WARNING],
        fail_count=counts[STATUS_FAIL],
        timeout_count=counts[STATUS_TIMEOUT],
    )

    return decision, counts, rows, blocked_legs, blocked_reasons


def _print_fallback(decision: str, counts: dict[str, int]) -> None:
    """Plain print when Rich unavailable or not TTY."""
    print(f"\nDecision: {decision}")
    print(
        f"Counts: pass={counts['pass']} warning={counts['warning']} fail={counts['fail']} timeout={counts['timeout']}"
    )


# ── CLI ────────────────────────────────────────────────────────────────────────


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Deprecated: use `tools bmt wait` instead. Kept for backwards compatibility."""
    p = sub.add_parser("wait", help="Poll for verdicts and aggregate results (deprecated: use tools bmt wait)")
    p.add_argument("--manifest", required=True, help="JSON manifest from trigger step")
    p.add_argument("--timeout-sec", required=True, type=int)
    p.add_argument("--poll-interval-sec", default=30, type=int)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> str:
    """Poll for verdict files (via current.json pointer), aggregate results, and output decision.

    Returns the decision string (e.g. STATUS_PASS). Caller should exit 0 for pass, non-zero otherwise.
    """
    bucket = _require_env("GCS_BUCKET")
    github_output = (os.environ.get("GITHUB_OUTPUT") or "").strip() or None
    config_root = Path(os.environ.get("BMT_CONFIG_ROOT", DEFAULT_CONFIG_ROOT))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    bucket_root = bucket_root_uri(bucket)
    legs = _parse_manifest(args.manifest, config_root, bucket_root)
    if not legs:
        raise RuntimeError("Empty manifest — nothing to wait for")

    pending: dict[str, TriggerLeg] = {leg.run_id: leg for leg in legs}
    prefix_groups = _group_by_prefix(legs)
    deadline = time.monotonic() + args.timeout_sec
    print(f"Waiting for {len(pending)} verdict(s), timeout={args.timeout_sec}s, poll={args.poll_interval_sec}s")

    collected = _poll_and_collect(
        pending, prefix_groups, bucket_root, bucket, deadline, args.poll_interval_sec, len(legs)
    )

    decision, counts, rows, blocked_legs, blocked_reasons = _aggregate(collected)

    _write_aggregate_step_summary(
        summary_path=summary_path,
        decision=decision,
        rows=rows,
        counts=counts,
        blocked_legs=blocked_legs,
        blocked_reasons=blocked_reasons,
    )

    if sys.stdout.isatty():
        try:
            from rich.console import Console
            from rich.table import Table

            t = Table(title="Verdict summary")
            t.add_column("Decision", style="bold")
            t.add_column("pass", style="green")
            t.add_column("warning", style="yellow")
            t.add_column("fail", style="red")
            t.add_column("timeout", style="red")
            t.add_row(
                decision,
                str(counts["pass"]),
                str(counts["warning"]),
                str(counts["fail"]),
                str(counts["timeout"]),
            )
            Console().print(t)
        except ImportError:
            _print_fallback(decision, counts)
    else:
        _print_fallback(decision, counts)

    _write_github_output(github_output, "decision", decision)
    _write_github_output(github_output, "pass_count", str(counts[STATUS_PASS]))
    _write_github_output(github_output, "warning_count", str(counts[STATUS_WARNING]))
    _write_github_output(github_output, "fail_count", str(counts[STATUS_FAIL]))
    _write_github_output(github_output, "timeout_count", str(counts[STATUS_TIMEOUT]))
    _write_github_output(github_output, "blocked_legs", ",".join(sorted(blocked_legs)))
    _write_github_output(github_output, "blocked_reasons", ",".join(sorted(blocked_reasons)))
    return decision

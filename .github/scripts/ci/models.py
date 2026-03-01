from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

# ── Status values ──────────────────────────────────────────────────────────────
STATUS_PASS = "pass"
STATUS_WARNING = "warning"
STATUS_FAIL = "fail"
STATUS_TIMEOUT = "timeout"
VALID_STATUSES = frozenset({STATUS_PASS, STATUS_WARNING, STATUS_FAIL, STATUS_TIMEOUT})
NON_BLOCKING_STATUSES = frozenset({STATUS_PASS, STATUS_WARNING})

# ── Final gate decisions ───────────────────────────────────────────────────────
DECISION_ACCEPTED = "accepted"
DECISION_ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
DECISION_REJECTED = "rejected"
DECISION_TIMEOUT = "timeout"

# ── Reason codes ───────────────────────────────────────────────────────────────
# Cloud-authoritative: set by the VM manager, round-tripped to CI via canonical verdict JSON.
# CI-transport: set by CI when the cloud verdict cannot be obtained or validated.

# CI-transport reasons
REASON_TRIGGER_WRITE_FAILED = "trigger_write_failed"
REASON_VERDICT_MISSING = "verdict_missing"
REASON_VERDICT_INVALID = "verdict_invalid"
REASON_VERDICT_RUN_ID_MISMATCH = "verdict_run_id_mismatch"
REASON_VERDICT_TIMEOUT = "verdict_timeout"
REASON_INVALID_STATUS = "invalid_status"
REASON_CI_DRIVER_EXCEPTION = "ci_driver_exception"
REASON_VM_NOT_RUNNING = "vm_not_running"
REASON_VM_LOCKED = "vm_locked"

REASON_UNKNOWN = "unknown"

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


# ── URI helpers ────────────────────────────────────────────────────────────────


def bucket_uri(bucket_root: str, rel_path: str) -> str:
    """Append a relative path to a bucket root URI."""
    return f"{bucket_root}/{rel_path.lstrip('/')}"


def code_bucket_root_uri(bucket: str) -> str:
    """Code bucket root: gs://<bucket>/code."""
    return f"gs://{bucket}/code"


def runtime_bucket_root_uri(bucket: str) -> str:
    """Runtime bucket root: gs://<bucket>/runtime."""
    return f"gs://{bucket}/runtime"


# ── Status / run-id helpers ────────────────────────────────────────────────────


def normalize_status(raw: str) -> str | None:
    """Return a valid status string or None if invalid."""
    value = (raw or "").strip().lower()
    return value if value in VALID_STATUSES else None


def sanitize_run_id(raw: str) -> str:
    """Sanitize run_id for use in paths (safe chars, max length)."""
    value = _RUN_ID_SAFE.sub("-", raw.strip())
    value = value.strip("-._")
    if not value:
        raise ValueError("run_id is empty after sanitization")
    return value[:200]


def snapshot_verdict_uri(bucket_root: str, results_prefix: str, run_id: str) -> str:
    """Build the GCS URI for a verdict in the pointer-based layout: snapshots/<run_id>/ci_verdict.json."""
    cleaned_prefix = results_prefix.rstrip("/")
    safe_run_id = sanitize_run_id(run_id)
    return bucket_uri(bucket_root, f"{cleaned_prefix}/snapshots/{safe_run_id}/ci_verdict.json")


def current_pointer_uri(bucket_root: str, results_prefix: str) -> str:
    """Build the GCS URI for the current.json pointer under a results prefix."""
    cleaned = results_prefix.rstrip("/")
    return bucket_uri(bucket_root, f"{cleaned}/current.json")


def run_trigger_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    """Build GCS URI for one run trigger file under runtime root."""
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/runs/{safe_run_id}.json")


def run_handshake_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    """Build GCS URI for VM handshake ack under runtime root."""
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/acks/{safe_run_id}.json")


def run_status_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    """Build GCS URI for VM status file under runtime root."""
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/status/{safe_run_id}.json")


# ── Decision helpers ───────────────────────────────────────────────────────────


def decision_for_counts(
    pass_count: int,
    warning_count: int,
    fail_count: int,
    timeout_count: int,
) -> str:
    if timeout_count > 0:
        return DECISION_TIMEOUT
    if fail_count > 0:
        return DECISION_REJECTED
    if warning_count > 0:
        return DECISION_ACCEPTED_WITH_WARNINGS
    if pass_count > 0:
        return DECISION_ACCEPTED
    return DECISION_TIMEOUT


def decision_exit(decision: str) -> int:
    return 0 if decision in {DECISION_ACCEPTED, DECISION_ACCEPTED_WITH_WARNINGS} else 1


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

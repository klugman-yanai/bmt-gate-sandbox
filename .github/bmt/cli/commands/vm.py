"""GCP VM lifecycle commands: start, sync metadata, wait for handshake."""

from __future__ import annotations

import json
import os
import tempfile
import time
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

from cli import gcloud, models
from cli.shared import require_env, write_github_output

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _is_truthy(raw: str | None) -> bool:
    value = (raw or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _instance_status(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    return str(status).strip() if status is not None else ""


def _last_start_timestamp(payload: dict[str, Any]) -> str | None:
    raw = payload.get("lastStartTimestamp")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _metadata_items(payload: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return out
    items = metadata.get("items")
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _vm_status(project: str, zone: str, instance_name: str) -> str:
    if not project or not zone or not instance_name:
        return "unknown"
    try:
        payload = gcloud.vm_describe(project, zone, instance_name)
    except gcloud.GcloudError:
        return "unknown"
    status = payload.get("status")
    return str(status).strip() if status is not None else "unknown"


def _serial_tail(project: str, zone: str, instance_name: str, lines: int = 50) -> str:
    if not project or not zone or not instance_name:
        return "<serial-unavailable: missing GCP_PROJECT/GCP_ZONE/BMT_VM_NAME>"
    try:
        serial = gcloud.vm_serial_output_retry(project, zone, instance_name, attempts=4, base_delay_sec=2.0)
    except gcloud.GcloudError as exc:
        return f"<serial-unavailable: {exc}>"
    tail = "\n".join(serial.splitlines()[-lines:])
    return tail.strip() or "<serial-empty>"


# ---------------------------------------------------------------------------
# start-vm
# ---------------------------------------------------------------------------


def run_start() -> None:
    """Start the BMT VM. Reads GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, BMT_ALLOW_MANUAL_VM_START from env."""
    timeout_sec = int(os.environ.get("BMT_VM_START_TIMEOUT_SEC", "180"))
    poll_interval_sec = 5
    stabilization_sec = int(os.environ.get("BMT_VM_STABILIZATION_SEC", "45"))
    recovery_attempts_max = int(os.environ.get("BMT_VM_START_RECOVERY_ATTEMPTS", "2"))
    terminal_recovery_statuses = {"TERMINATED", "STOPPED", "SUSPENDED"}

    in_actions = _is_truthy(os.environ.get("GITHUB_ACTIONS"))
    if not in_actions and not _is_truthy(os.environ.get("BMT_ALLOW_MANUAL_VM_START")):
        raise RuntimeError(
            "Manual VM start is blocked by policy. Allowed purposes: debugging, maintenance, testing. "
            "Set BMT_ALLOW_MANUAL_VM_START=1 for explicit manual starts."
        )

    project = require_env("GCP_PROJECT")
    zone = require_env("GCP_ZONE")
    instance_name = require_env("BMT_VM_NAME")
    before: dict[str, Any] | None = None
    before_status = ""
    before_last_start: str | None = None
    try:
        before = gcloud.vm_describe(project, zone, instance_name)
        before_status = _instance_status(before)
        before_last_start = _last_start_timestamp(before)
    except gcloud.GcloudError as exc:
        print(f"::warning::Could not describe VM before start: {exc}")

    def _is_idempotent_start_error(exc: gcloud.GcloudError) -> bool:
        text = str(exc).lower()
        tokens = (
            "already running",
            "already started",
            "is starting",
            "being started",
            "operation in progress",
            "currently stopping",
            "is stopping",
            "not ready",
            "resource not ready",
            "resource fingerprint changed",
            "please try again",
        )
        return any(token in text for token in tokens)

    def _request_start(reason: str) -> bool:
        try:
            gcloud.vm_start(project, zone, instance_name)
        except gcloud.GcloudError as exc:
            if _is_idempotent_start_error(exc):
                print(f"::warning::{exc}")
                print(f"VM start treated as idempotent while {reason}; continuing readiness checks.")
                return False
            print(f"::error::{exc}")
            raise
        print(f"Start command submitted for VM {instance_name} (zone={zone}) [{reason}]")
        return True
    print(
        f"Waiting for RUNNING state (timeout={timeout_sec}s, poll={poll_interval_sec}s); "
        f"previous status={before_status or '<unknown>'} previous lastStart={before_last_start or '<none>'}"
    )

    deadline = time.monotonic() + timeout_sec
    last_seen_status = ""
    last_seen_start: str | None = None
    recovery_attempts = 0
    recovery_pending = False
    terminal_polls = 0

    def _attempt_recovery_start(trigger_status: str, phase: str) -> None:
        nonlocal before_last_start, before_status, recovery_attempts, recovery_pending, terminal_polls
        recovery_attempts += 1
        if recovery_attempts > recovery_attempts_max:
            raise RuntimeError(
                "VM became unstable and recovery attempts were exhausted; "
                f"phase={phase}; status={trigger_status}; max_recovery_attempts={recovery_attempts_max}"
            )
        print(
            "::warning::"
            f"VM not ready; status={trigger_status}; attempting recovery start "
            f"{recovery_attempts}/{recovery_attempts_max} ({phase})"
        )
        before_status = trigger_status
        before_last_start = last_seen_start
        recovery_pending = True
        terminal_polls = 0
        _request_start(f"recovery attempt {recovery_attempts} ({phase})")

    initial_start_submitted = _request_start("initial start")
    if not initial_start_submitted and before_status != "RUNNING":
        recovery_pending = True

    while time.monotonic() < deadline:
        describe = gcloud.vm_describe(project, zone, instance_name)
        last_seen_status = _instance_status(describe)
        last_seen_start = _last_start_timestamp(describe)
        if last_seen_status in terminal_recovery_statuses:
            terminal_polls += 1
        else:
            terminal_polls = 0
        running = last_seen_status == "RUNNING"
        start_advanced = before_last_start is None or (
            last_seen_start is not None and last_seen_start != before_last_start
        )
        already_running = before_status == "RUNNING" and running
        running_after_recovery = recovery_pending and running
        if running and (start_advanced or already_running or running_after_recovery):
            recovery_pending = False
            print(
                f"VM ready: status={last_seen_status} lastStartTimestamp={last_seen_start or '<none>'} "
                f"(previous={before_last_start or '<none>'})"
            )
            if stabilization_sec <= 0:
                return
            print(f"Stabilizing RUNNING state for {stabilization_sec}s (poll={poll_interval_sec}s)")
            stable_deadline = time.monotonic() + stabilization_sec
            unstable_status = ""
            while time.monotonic() < stable_deadline:
                stable_describe = gcloud.vm_describe(project, zone, instance_name)
                stable_status = _instance_status(stable_describe)
                if stable_status != "RUNNING":
                    unstable_status = stable_status or "<unknown>"
                    break
                remaining = stable_deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(max(1, poll_interval_sec), remaining))
            if unstable_status:
                _attempt_recovery_start(unstable_status, "stabilization")
                time.sleep(max(1, poll_interval_sec))
                continue
            print("VM stabilization passed.")
            return
        if last_seen_status in terminal_recovery_statuses and (recovery_pending or terminal_polls >= 2):
            _attempt_recovery_start(last_seen_status or "<unknown>", "readiness")
        time.sleep(max(1, poll_interval_sec))

    message = (
        "VM did not reach ready state after start command; "
        f"last status={last_seen_status or '<unknown>'} "
        f"lastStartTimestamp={last_seen_start or '<none>'} "
        f"previousLastStart={before_last_start or '<none>'} "
        f"recoveryAttempts={recovery_attempts}/{recovery_attempts_max}"
    )
    raise RuntimeError(message)


# ---------------------------------------------------------------------------
# sync-vm-metadata
# ---------------------------------------------------------------------------


def _build_desired_metadata(
    bucket: str,
    repo_root: str,
    startup_wrapper_script: str,
) -> tuple[dict[str, str], str]:
    """Return (metadata_dict, startup_script_content)."""
    metadata = {
        "GCS_BUCKET": bucket,
        "BMT_REPO_ROOT": repo_root,
        "startup-script-url": "",
    }
    return metadata, startup_wrapper_script


def _load_startup_wrapper_script() -> str:
    """Load packaged startup wrapper text shipped with the cli package."""
    try:
        wrapper = importlib_resources.files("cli.resources").joinpath("startup_wrapper.sh")
        script_content = wrapper.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise RuntimeError("Missing packaged startup wrapper resource: cli.resources/startup_wrapper.sh") from exc
    if not script_content.strip():
        raise RuntimeError("Packaged startup wrapper resource is empty: cli.resources/startup_wrapper.sh")
    return script_content


def run_sync_metadata() -> None:
    """Sync startup-critical VM metadata and inline startup wrapper from package resources."""
    project = require_env("GCP_PROJECT")
    zone = require_env("GCP_ZONE")
    instance_name = require_env("BMT_VM_NAME")
    bucket = require_env("GCS_BUCKET")
    repo_root = (os.environ.get("BMT_REPO_ROOT") or "/opt/bmt").strip() or "/opt/bmt"
    startup_wrapper_script = _load_startup_wrapper_script()
    code_root = models.code_bucket_root_uri(bucket)

    required_code_objects = (
        f"{code_root}/pyproject.toml",
        f"{code_root}/uv.lock",
        f"{code_root}/bootstrap/startup_example.sh",
        f"{code_root}/vm_watcher.py",
        f"{code_root}/root_orchestrator.py",
        f"{code_root}/_tools/uv/linux-x86_64/uv",
        f"{code_root}/_tools/uv/linux-x86_64/uv.sha256",
    )
    missing_objects = [uri for uri in required_code_objects if not gcloud.gcs_exists(uri)]
    if missing_objects:
        joined = "\n".join(f"  - {uri}" for uri in missing_objects)
        raise RuntimeError(
            "Missing required code objects in bucket namespace. "
            "Sync code mirror first (just sync-remote && just verify-sync):\n"
            f"{joined}"
        )

    # Fail-fast: reject non-empty legacy BMT_BUCKET_PREFIX in VM metadata
    try:
        described = gcloud.vm_describe(project, zone, instance_name)
    except gcloud.GcloudError:
        described = None
    if described:
        current = _metadata_items(described)
        legacy_prefix = current.get("BMT_BUCKET_PREFIX", "").strip()
        if legacy_prefix:
            raise RuntimeError(
                f"Legacy BMT_BUCKET_PREFIX='{legacy_prefix}' found in VM metadata for {instance_name}. "
                "BMT_BUCKET_PREFIX has been removed. Clear the VM metadata key before proceeding."
            )

    desired_metadata, desired_script = _build_desired_metadata(bucket, repo_root, startup_wrapper_script)

    force = _is_truthy(os.environ.get("BMT_FORCE_SYNC"))
    if not force and described:
        current = _metadata_items(described)
        if (
            all(current.get(k) == v for k, v in desired_metadata.items())
            and current.get("startup-script", "").strip() == desired_script.strip()
        ):
            print(f"VM metadata for {instance_name} already in sync; skipping. Use --force to re-sync.")
            return

    metadata = {
        "GCS_BUCKET": bucket,
        "BMT_REPO_ROOT": repo_root,
        "startup-script-url": "",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="bmt_startup_wrapper_") as tmp_dir:
            wrapper_path = Path(tmp_dir) / "startup_wrapper.sh"
            wrapper_path.write_text(desired_script, encoding="utf-8")
            gcloud.vm_add_metadata(
                project,
                zone,
                instance_name,
                metadata,
                metadata_files={"startup-script": wrapper_path},
            )
        described = gcloud.vm_describe(project, zone, instance_name)
    except gcloud.GcloudError as exc:
        print(f"::error::{exc}")
        raise

    items = _metadata_items(described)
    if items.get("GCS_BUCKET", "").strip() != bucket:
        raise RuntimeError("VM metadata verification failed: GCS_BUCKET did not persist.")
    if items.get("BMT_REPO_ROOT", "").strip() != repo_root:
        raise RuntimeError("VM metadata verification failed: BMT_REPO_ROOT did not persist.")
    if not (items.get("startup-script", "")).strip():
        raise RuntimeError("VM metadata verification failed: startup-script is missing/empty.")
    if (items.get("startup-script-url", "")).strip():
        raise RuntimeError("VM metadata verification failed: startup-script-url is not cleared.")

    print(f"Synced VM metadata for {instance_name}: GCS_BUCKET={bucket} BMT_REPO_ROOT={repo_root}")
    print("Updated inline startup-script from packaged resource cli.resources/startup_wrapper.sh")


# ---------------------------------------------------------------------------
# wait-handshake
# ---------------------------------------------------------------------------


def run_wait_handshake() -> None:
    """Wait for VM handshake ack written under triggers/acks/<workflow_run_id>.json."""
    bucket = require_env("GCS_BUCKET")
    workflow_run_id = require_env("GITHUB_RUN_ID")
    github_output = require_env("GITHUB_OUTPUT")
    timeout_sec = int(os.environ.get("BMT_HANDSHAKE_TIMEOUT_SEC", "180"))
    poll_interval_sec = 5
    project = os.environ.get("GCP_PROJECT", "")
    zone = os.environ.get("GCP_ZONE", "")
    instance_name = os.environ.get("BMT_VM_NAME", "")

    runtime_bucket_root = models.runtime_bucket_root_uri(bucket)
    ack_uri = models.run_handshake_uri(runtime_bucket_root, workflow_run_id)
    trigger_uri = models.run_trigger_uri(runtime_bucket_root, workflow_run_id)
    runtime_status_uri = models.run_status_uri(runtime_bucket_root, workflow_run_id)

    print(f"Waiting for VM handshake ack at {ack_uri} (timeout={timeout_sec}s, poll every {poll_interval_sec}s)")
    print(f"Trigger file (VM reads this): {trigger_uri}")
    print(f"Expected runtime status path: {runtime_status_uri}")
    print(f"Runtime namespace root: {runtime_bucket_root}")
    print("Handshake confirms VM pickup only; final BMT Gate status updates after VM execution completes.")

    trigger_exists_initially = gcloud.gcs_exists(trigger_uri)
    if not trigger_exists_initially:
        raise RuntimeError(f"Trigger file missing before handshake wait: {trigger_uri}")

    deadline = time.monotonic() + timeout_sec
    payload: dict[str, Any] | None = None
    last_error: str | None = None
    last_progress = 0.0
    last_vm_status = _vm_status(project, zone, instance_name)
    trigger_exists = trigger_exists_initially

    while time.monotonic() < deadline:
        elapsed = time.monotonic() - (deadline - timeout_sec)
        payload, error = gcloud.download_json(ack_uri)
        if payload is not None:
            break
        last_error = error
        if elapsed - last_progress >= 15:
            trigger_exists = gcloud.gcs_exists(trigger_uri)
            last_vm_status = _vm_status(project, zone, instance_name)
            runtime_status_exists = gcloud.gcs_exists(runtime_status_uri)
            remaining = max(0, int(deadline - time.monotonic()))
            print(
                f"  ... waiting {int(elapsed)}s / {timeout_sec}s timeout (remaining ~{remaining}s) "
                f"vm_status={last_vm_status} trigger_exists={trigger_exists} "
                f"runtime_status_exists={runtime_status_exists}"
            )
            last_progress = elapsed
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval_sec, remaining))

    if payload is None:
        trigger_exists = gcloud.gcs_exists(trigger_uri)
        last_vm_status = _vm_status(project, zone, instance_name)
        runtime_status_exists = gcloud.gcs_exists(runtime_status_uri)
        reason = "unknown"
        if not trigger_exists:
            reason = "trigger_missing"
        elif last_vm_status != "RUNNING":
            reason = "vm_not_running"
        elif last_error:
            reason = "ack_unreadable"
        else:
            reason = "ack_not_written"
        serial = _serial_tail(project, zone, instance_name, lines=40)
        details = f"; last_error={last_error}" if last_error else ""
        raise RuntimeError(
            f"Timed out waiting for VM handshake ack at {ack_uri}{details}; "
            f"reason={reason}; vm_status={last_vm_status}; trigger_exists={trigger_exists}; "
            f"runtime_status_exists={runtime_status_exists}\n"
            f"--- serial tail ---\n{serial}"
        )

    accepted_legs = payload.get("accepted_legs", [])
    if not isinstance(accepted_legs, list):
        accepted_legs = []
    rejected_legs = payload.get("rejected_legs", [])
    if not isinstance(rejected_legs, list):
        rejected_legs = []

    requested_legs_raw = payload.get("requested_legs")
    requested_count = _as_int(payload.get("requested_leg_count"), len(requested_legs_raw) if isinstance(requested_legs_raw, list) else len(accepted_legs))
    accepted_count = _as_int(payload.get("accepted_leg_count"), len(accepted_legs))
    requested_legs: list[dict[str, Any]]
    if isinstance(requested_legs_raw, list):
        requested_legs = [entry for entry in requested_legs_raw if isinstance(entry, dict)]
    else:
        # Backward-compatible synthesis when watcher payload predates support-resolution v2.
        requested_legs = []
        for idx, leg in enumerate(accepted_legs):
            if not isinstance(leg, dict):
                continue
            requested_legs.append(
                {
                    "index": idx,
                    "project": str(leg.get("project", "?")),
                    "bmt_id": str(leg.get("bmt_id", "?")),
                    "run_id": str(leg.get("run_id", "?")),
                    "decision": "accepted",
                    "reason": None,
                }
            )
        for rej in rejected_legs:
            if not isinstance(rej, dict):
                continue
            requested_legs.append(
                {
                    "index": _as_int(rej.get("index"), len(requested_legs)),
                    "project": str(rej.get("project", "?")),
                    "bmt_id": str(rej.get("bmt_id", "?")),
                    "run_id": str(rej.get("run_id", "?")),
                    "decision": "rejected",
                    "reason": str(rej.get("reason") or "invalid_leg_type"),
                }
            )

    support_resolution_version = str(
        payload.get("support_resolution_version")
        or ("v2" if isinstance(requested_legs_raw, list) else "v1")
    )
    run_disposition = str(
        payload.get("run_disposition")
        or ("accepted" if accepted_count > 0 else "accepted_but_empty")
    )

    write_github_output(github_output, "handshake_uri", ack_uri)
    write_github_output(github_output, "handshake_payload", json.dumps(payload, separators=(",", ":")))
    write_github_output(github_output, "handshake_requested_leg_count", str(requested_count))
    write_github_output(github_output, "handshake_accepted_leg_count", str(accepted_count))
    write_github_output(github_output, "handshake_accepted_legs", json.dumps(accepted_legs, separators=(",", ":")))
    write_github_output(github_output, "handshake_support_resolution_version", support_resolution_version)
    write_github_output(github_output, "handshake_requested_legs", json.dumps(requested_legs, separators=(",", ":")))
    write_github_output(github_output, "handshake_rejected_legs", json.dumps(rejected_legs, separators=(",", ":")))
    write_github_output(github_output, "handshake_run_disposition", run_disposition)

    print(f"VM handshake received: requested={requested_count} accepted={accepted_count} vm_status={last_vm_status}")

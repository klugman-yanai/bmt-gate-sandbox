"""GCP VM lifecycle commands: start, sync metadata, wait for handshake."""

from __future__ import annotations

import json
import os
import tempfile
import time
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

from cli import shared
from cli.gh_output import gh_error, gh_warning
from cli.shared import get_config, require_env, write_github_output

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
        payload = shared.vm_describe(project, zone, instance_name)
    except shared.GcloudError:
        return "unknown"
    status = payload.get("status")
    return str(status).strip() if status is not None else "unknown"


def _serial_tail(project: str, zone: str, instance_name: str, lines: int = 50) -> str:
    if not project or not zone or not instance_name:
        return "<serial-unavailable: missing GCP_PROJECT/GCP_ZONE/BMT_VM_NAME>"
    try:
        serial = shared.vm_serial_output_retry(
            project, zone, instance_name, attempts=4, base_delay_sec=2.0
        )
    except shared.GcloudError as exc:
        return f"<serial-unavailable: {exc}>"
    tail = "\n".join(serial.splitlines()[-lines:])
    return tail.strip() or "<serial-empty>"


# ---------------------------------------------------------------------------
# select-available-vm
# ---------------------------------------------------------------------------


def run_select_available_vm() -> None:
    """Select workflow-owned VM (BMT_VM_NAME) and decide reuse/start behavior."""
    cfg = get_config()
    cfg.require_gcp()
    project = cfg.gcp_project
    zone = cfg.gcp_zone
    github_output = require_env("GITHUB_OUTPUT")

    pool = [cfg.bmt_vm_name]

    print(f"VM pool ({len(pool)} instance(s)): {pool}")
    statuses: dict[str, str] = {}
    for vm_name in pool:
        status = _vm_status(project, zone, vm_name)
        statuses[vm_name] = status
        print(f"  {vm_name}: {status}")
        # Prefer TERMINATED: start this VM and assign our trigger (e.g. vm-1 when vm-0 is STOPPING).
        if status == "TERMINATED":
            print(f"Selected VM: {vm_name} (TERMINATED — will start and assign this run)")
            write_github_output(github_output, "selected_vm", vm_name)
            write_github_output(github_output, "vm_reused_running", "false")
            return

    # No TERMINATED VM (single VM is already RUNNING):
    # reuse first RUNNING VM so we don't fail; handoff uses longer handshake timeout.
    for vm_name in pool:
        if statuses.get(vm_name) == "RUNNING":
            print(f"Selected VM: {vm_name} (RUNNING — reusing to avoid cold-start timeout)")
            gh_warning(
                f"No TERMINATED VM in pool; reusing RUNNING VM {vm_name}. "
                "Handshake may take longer until the VM picks up this run's trigger."
            )
            write_github_output(github_output, "selected_vm", vm_name)
            write_github_output(github_output, "vm_reused_running", "true")
            return

    status_summary = ", ".join(f"{v}={s}" for v, s in statuses.items())
    msg = (
        f"No selectable VM state for configured BMT_VM_NAME ({status_summary}). "
        "VM must be TERMINATED or RUNNING; wait for state stabilization and re-trigger."
    )
    gh_error(f"No BMT VM is available. {msg}")
    gh_warning(msg)
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# start-vm
# ---------------------------------------------------------------------------


def run_start() -> None:
    """Start the BMT VM. GCP/BMT identity from config; timeouts and BMT_ALLOW_MANUAL_VM_START from env."""
    cfg = get_config()
    cfg.require_gcp()
    timeout_sec = int(os.environ.get("BMT_VM_START_TIMEOUT_SEC", "180"))
    poll_interval_sec = 5
    stabilization_sec = int(os.environ.get("BMT_VM_STABILIZATION_SEC", "45"))
    recovery_attempts_max = int(os.environ.get("BMT_VM_START_RECOVERY_ATTEMPTS", "2"))

    in_actions = _is_truthy(os.environ.get("GITHUB_ACTIONS"))
    if not in_actions and not _is_truthy(os.environ.get("BMT_ALLOW_MANUAL_VM_START")):
        raise RuntimeError(
            "Manual VM start is blocked by policy. Allowed purposes: debugging, maintenance, testing. "
            "Set BMT_ALLOW_MANUAL_VM_START=1 for explicit manual starts."
        )

    project = cfg.gcp_project
    zone = cfg.gcp_zone
    instance_name = cfg.bmt_vm_name
    before: dict[str, Any] | None = None
    before_status = ""
    before_last_start: str | None = None
    try:
        before = shared.vm_describe(project, zone, instance_name)
        before_status = _instance_status(before)
        before_last_start = _last_start_timestamp(before)
    except shared.GcloudError as exc:
        gh_warning(f"Could not describe VM before start: {exc}")

    def _is_idempotent_start_error(exc: shared.GcloudError) -> bool:
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

    def _request_start(reason: str) -> None:
        try:
            shared.vm_start(project, zone, instance_name)
        except shared.GcloudError as exc:
            if _is_idempotent_start_error(exc):
                gh_warning(str(exc))
                print(
                    f"VM start treated as idempotent while {reason}; continuing readiness checks."
                )
                return
            gh_error(str(exc))
            raise
        print(f"Start command submitted for VM {instance_name} (zone={zone}) [{reason}]")

    _request_start("initial start")
    print(
        f"Waiting for RUNNING state (timeout={timeout_sec}s, poll={poll_interval_sec}s); "
        f"previous status={before_status or '<unknown>'} previous lastStart={before_last_start or '<none>'}"
    )

    deadline = time.monotonic() + timeout_sec
    last_seen_status = ""
    last_seen_start: str | None = None
    recovery_attempts = 0
    recovery_pending = False
    stop_retry_done = False  # only one wait-for-TERMINATED + retry per run
    while time.monotonic() < deadline:
        describe = shared.vm_describe(project, zone, instance_name)
        last_seen_status = _instance_status(describe)
        last_seen_start = _last_start_timestamp(describe)

        # If VM is STOPPING (e.g. previous run self-stopped), wait for TERMINATED then start again
        if last_seen_status == "STOPPING" and not stop_retry_done:
            stop_deadline = time.monotonic() + min(120, max(0, int(deadline - time.monotonic())))
            gh_warning(
                "VM is STOPPING (e.g. from previous run); waiting for TERMINATED then retrying start."
            )
            while time.monotonic() < stop_deadline:
                describe = shared.vm_describe(project, zone, instance_name)
                s = _instance_status(describe)
                if s == "TERMINATED":
                    print("VM reached TERMINATED; issuing retry start.")
                    stop_retry_done = True
                    _request_start("retry after VM stopped")
                    break
                remaining = stop_deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        "VM remained in STOPPING state; could not retry start within 120s. "
                        "Try re-running the job once the VM has fully stopped."
                    )
                time.sleep(min(poll_interval_sec, remaining))
            continue

        # If VM is already TERMINATED on first poll (e.g. stopped before we could start), issue start once
        if last_seen_status == "TERMINATED" and not stop_retry_done:
            gh_warning("VM is TERMINATED; issuing retry start.")
            stop_retry_done = True
            _request_start("retry after VM stopped")
            continue

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
                stable_describe = shared.vm_describe(project, zone, instance_name)
                stable_status = _instance_status(stable_describe)
                if stable_status != "RUNNING":
                    unstable_status = stable_status or "<unknown>"
                    break
                remaining = stable_deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(max(1, poll_interval_sec), remaining))
            if unstable_status:
                recovery_attempts += 1
                if recovery_attempts > recovery_attempts_max:
                    raise RuntimeError(
                        "VM became unstable during stabilization window and recovery attempts were exhausted; "
                        f"status={unstable_status}; max_recovery_attempts={recovery_attempts_max}"
                    )
                gh_warning(
                    f"VM became unstable during stabilization window; status={unstable_status}; "
                    f"attempting recovery start {recovery_attempts}/{recovery_attempts_max}"
                )
                before_status = unstable_status
                before_last_start = last_seen_start
                recovery_pending = True
                _request_start(f"recovery attempt {recovery_attempts}")
                continue
            print("VM stabilization passed.")
            return
        time.sleep(max(1, poll_interval_sec))

    message = (
        "VM did not reach ready state after start command; "
        f"last status={last_seen_status or '<unknown>'} "
        f"lastStartTimestamp={last_seen_start or '<none>'} "
        f"previousLastStart={before_last_start or '<none>'}"
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
        raise RuntimeError(
            "Missing packaged startup wrapper resource: cli.resources/startup_wrapper.sh"
        ) from exc
    if not script_content.strip():
        raise RuntimeError(
            "Packaged startup wrapper resource is empty: cli.resources/startup_wrapper.sh"
        )
    return script_content


def run_sync_metadata() -> None:
    """Sync startup-critical VM metadata and inline startup wrapper from package resources."""
    cfg = get_config()
    cfg.require_gcp()
    project = cfg.gcp_project
    zone = cfg.gcp_zone
    instance_name = cfg.bmt_vm_name
    bucket = cfg.gcs_bucket
    repo_root = (os.environ.get("BMT_REPO_ROOT") or "/opt/bmt").strip() or "/opt/bmt"
    startup_wrapper_script = _load_startup_wrapper_script()
    code_root = shared.code_bucket_root_uri(bucket)

    required_code_objects = (
        f"{code_root}/pyproject.toml",
        f"{code_root}/uv.lock",
        f"{code_root}/bootstrap/startup_example.sh",
        f"{code_root}/vm_watcher.py",
        f"{code_root}/root_orchestrator.py",
        f"{code_root}/_tools/uv/linux-x86_64/uv",
        f"{code_root}/_tools/uv/linux-x86_64/uv.sha256",
    )
    missing_objects = [uri for uri in required_code_objects if not shared.gcs_exists(uri)]
    if missing_objects:
        joined = "\n".join(f"  - {uri}" for uri in missing_objects)
        raise RuntimeError(
            "Missing required code objects in bucket namespace. "
            "Sync code mirror first (just sync-remote && just verify-sync):\n"
            f"{joined}"
        )

    # Fail-fast: reject non-empty legacy BMT_BUCKET_PREFIX in VM metadata
    try:
        described = shared.vm_describe(project, zone, instance_name)
    except shared.GcloudError:
        described = None
    if described:
        current = _metadata_items(described)
        legacy_prefix = current.get("BMT_BUCKET_PREFIX", "").strip()
        if legacy_prefix:
            raise RuntimeError(
                f"Legacy BMT_BUCKET_PREFIX='{legacy_prefix}' found in VM metadata for {instance_name}. "
                "BMT_BUCKET_PREFIX has been removed. Clear the VM metadata key before proceeding."
            )

    desired_metadata, desired_script = _build_desired_metadata(
        bucket, repo_root, startup_wrapper_script
    )

    force = _is_truthy(os.environ.get("BMT_FORCE_SYNC"))
    if not force and described:
        current = _metadata_items(described)
        if (
            all(current.get(k) == v for k, v in desired_metadata.items())
            and current.get("startup-script", "").strip() == desired_script.strip()
        ):
            print(
                f"VM metadata for {instance_name} already in sync; skipping. Use --force to re-sync."
            )
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
            shared.vm_add_metadata(
                project,
                zone,
                instance_name,
                metadata,
                metadata_files={"startup-script": wrapper_path},
            )
        described = shared.vm_describe(project, zone, instance_name)
    except shared.GcloudError as exc:
        gh_error(str(exc))
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
    cfg = get_config()
    cfg.require_gcp()
    bucket = cfg.gcs_bucket
    workflow_run_id = require_env("GITHUB_RUN_ID")
    github_output = require_env("GITHUB_OUTPUT")
    timeout_sec = cfg.bmt_handshake_timeout_sec
    if not (1 <= timeout_sec <= 3600):
        raise RuntimeError(f"BMT_HANDSHAKE_TIMEOUT_SEC must be 1-3600s, got {timeout_sec}")
    poll_interval_sec = 5
    project = cfg.gcp_project
    zone = cfg.gcp_zone
    instance_name = cfg.bmt_vm_name

    runtime_bucket_root = shared.runtime_bucket_root_uri(bucket)
    ack_uri = shared.run_handshake_uri(runtime_bucket_root, workflow_run_id)
    trigger_uri = shared.run_trigger_uri(runtime_bucket_root, workflow_run_id)
    runtime_status_uri = shared.run_status_uri(runtime_bucket_root, workflow_run_id)

    print(
        f"Waiting for VM handshake ack at {ack_uri} (timeout={timeout_sec}s, poll every {poll_interval_sec}s)"
    )
    print(f"Trigger file (VM reads this): {trigger_uri}")
    print(f"Expected runtime status path: {runtime_status_uri}")
    print(f"Runtime namespace root: {runtime_bucket_root}")
    print(
        "Handshake confirms VM pickup only; final BMT Gate status updates after VM execution completes."
    )

    trigger_exists_initially = shared.gcs_exists(trigger_uri)
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
        payload, error = shared.download_json(ack_uri)
        if payload is not None:
            break
        last_error = error
        if elapsed - last_progress >= 15:
            trigger_exists = shared.gcs_exists(trigger_uri)
            last_vm_status = _vm_status(project, zone, instance_name)
            runtime_status_exists = shared.gcs_exists(runtime_status_uri)
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
        trigger_exists = shared.gcs_exists(trigger_uri)
        last_vm_status = _vm_status(project, zone, instance_name)
        runtime_status_exists = shared.gcs_exists(runtime_status_uri)
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
    requested_count = _as_int(
        payload.get("requested_leg_count"),
        len(requested_legs_raw) if isinstance(requested_legs_raw, list) else len(accepted_legs),
    )
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
    write_github_output(
        github_output, "handshake_payload", json.dumps(payload, separators=(",", ":"))
    )
    write_github_output(github_output, "handshake_requested_leg_count", str(requested_count))
    write_github_output(github_output, "handshake_accepted_leg_count", str(accepted_count))
    write_github_output(
        github_output, "handshake_accepted_legs", json.dumps(accepted_legs, separators=(",", ":"))
    )
    write_github_output(
        github_output, "handshake_support_resolution_version", support_resolution_version
    )
    write_github_output(
        github_output, "handshake_requested_legs", json.dumps(requested_legs, separators=(",", ":"))
    )
    write_github_output(
        github_output, "handshake_rejected_legs", json.dumps(rejected_legs, separators=(",", ":"))
    )
    write_github_output(github_output, "handshake_run_disposition", run_disposition)

    print(
        f"VM handshake received: requested={requested_count} accepted={accepted_count} vm_status={last_vm_status}"
    )

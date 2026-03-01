from __future__ import annotations

import json
import time
from typing import Any

import click

from ci import models
from ci.adapters import gcloud_cli
from ci.github_output import write_github_output


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _vm_status(project: str, zone: str, instance_name: str) -> str:
    if not project or not zone or not instance_name:
        return "unknown"
    try:
        payload = gcloud_cli.vm_describe(project, zone, instance_name)
    except gcloud_cli.GcloudError:
        return "unknown"
    status = payload.get("status")
    return str(status).strip() if status is not None else "unknown"


def _serial_tail(project: str, zone: str, instance_name: str, lines: int = 50) -> str:
    if not project or not zone or not instance_name:
        return "<serial-unavailable: missing GCP_PROJECT/GCP_ZONE/BMT_VM_NAME>"
    try:
        serial = gcloud_cli.vm_serial_output_retry(project, zone, instance_name, attempts=4, base_delay_sec=2.0)
    except gcloud_cli.GcloudError as exc:
        return f"<serial-unavailable: {exc}>"
    tail = "\n".join(serial.splitlines()[-lines:])
    return tail.strip() or "<serial-empty>"


@click.command("wait-handshake")
@click.option("--bucket", required=True, envvar="GCS_BUCKET")
@click.option("--workflow-run-id", required=True, envvar="GITHUB_RUN_ID")
@click.option(
    "--timeout-sec",
    default=180,
    show_default=True,
    type=int,
    help="Must match config/env_contract.json defaults.BMT_HANDSHAKE_TIMEOUT_SEC when env unset.",
)
@click.option("--poll-interval-sec", default=5, show_default=True, type=int)
@click.option("--project", default="", envvar="GCP_PROJECT")
@click.option("--zone", default="", envvar="GCP_ZONE")
@click.option("--instance-name", default="", envvar="BMT_VM_NAME")
@click.option("--github-output", envvar="GITHUB_OUTPUT")
def command(
    bucket: str,
    workflow_run_id: str,
    timeout_sec: int,
    poll_interval_sec: int,
    project: str,
    zone: str,
    instance_name: str,
    github_output: str | None,
) -> None:
    """Wait for VM handshake ack written under triggers/acks/<workflow_run_id>.json."""
    if not github_output:
        raise RuntimeError("GITHUB_OUTPUT is required")

    runtime_bucket_root = models.runtime_bucket_root_uri(bucket)
    ack_uri = models.run_handshake_uri(runtime_bucket_root, workflow_run_id)
    trigger_uri = models.run_trigger_uri(runtime_bucket_root, workflow_run_id)
    runtime_status_uri = models.run_status_uri(runtime_bucket_root, workflow_run_id)

    print(f"Waiting for VM handshake ack at {ack_uri} (timeout={timeout_sec}s, poll every {poll_interval_sec}s)")
    print(f"Trigger file (VM reads this): {trigger_uri}")
    print(f"Expected runtime status path: {runtime_status_uri}")
    print(f"Runtime namespace root: {runtime_bucket_root}")

    trigger_exists_initially = gcloud_cli.gcs_exists(trigger_uri)
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
        payload, error = gcloud_cli.download_json(ack_uri)
        if payload is not None:
            break
        last_error = error
        if elapsed - last_progress >= 15:
            trigger_exists = gcloud_cli.gcs_exists(trigger_uri)
            last_vm_status = _vm_status(project, zone, instance_name)
            runtime_status_exists = gcloud_cli.gcs_exists(runtime_status_uri)
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
        trigger_exists = gcloud_cli.gcs_exists(trigger_uri)
        last_vm_status = _vm_status(project, zone, instance_name)
        runtime_status_exists = gcloud_cli.gcs_exists(runtime_status_uri)
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

    requested_count = _as_int(payload.get("requested_leg_count"), len(accepted_legs))
    accepted_count = _as_int(payload.get("accepted_leg_count"), len(accepted_legs))

    write_github_output(github_output, "handshake_uri", ack_uri)
    write_github_output(github_output, "handshake_payload", json.dumps(payload, separators=(",", ":")))
    write_github_output(github_output, "handshake_requested_leg_count", str(requested_count))
    write_github_output(github_output, "handshake_accepted_leg_count", str(accepted_count))
    write_github_output(github_output, "handshake_accepted_legs", json.dumps(accepted_legs, separators=(",", ":")))

    print(f"VM handshake received: requested={requested_count} accepted={accepted_count} vm_status={last_vm_status}")

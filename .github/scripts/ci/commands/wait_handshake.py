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


@click.command("wait-handshake")
@click.option("--bucket", required=True, envvar="GCS_BUCKET")
@click.option("--bucket-prefix", default="", envvar="BMT_BUCKET_PREFIX")
@click.option("--workflow-run-id", required=True, envvar="GITHUB_RUN_ID")
@click.option("--timeout-sec", default=180, show_default=True, type=int)
@click.option("--poll-interval-sec", default=5, show_default=True, type=int)
@click.option("--github-output", envvar="GITHUB_OUTPUT")
def command(
    bucket: str,
    bucket_prefix: str,
    workflow_run_id: str,
    timeout_sec: int,
    poll_interval_sec: int,
    github_output: str | None,
) -> None:
    """Wait for VM handshake ack written under triggers/acks/<workflow_run_id>.json."""
    if not github_output:
        raise RuntimeError("GITHUB_OUTPUT is required")

    bucket_root = models.bucket_root_uri(bucket, bucket_prefix)
    ack_uri = models.run_handshake_uri(bucket_root, bucket_prefix, workflow_run_id)
    trigger_uri = models.run_trigger_uri(bucket_root, bucket_prefix, workflow_run_id)

    print(f"Waiting for VM handshake ack at {ack_uri} (timeout={timeout_sec}s, poll every {poll_interval_sec}s)")
    print(f"Trigger file (VM reads this): {trigger_uri}")
    deadline = time.monotonic() + timeout_sec
    payload: dict[str, Any] | None = None
    last_error: str | None = None
    last_progress = 0.0

    while time.monotonic() < deadline:
        elapsed = time.monotonic() - (deadline - timeout_sec)
        payload, error = gcloud_cli.download_json(ack_uri)
        if payload is not None:
            break
        last_error = error
        if elapsed - last_progress >= 15:
            remaining = int(deadline - time.monotonic())
            print(f"  ... waiting {int(elapsed)}s / {timeout_sec}s timeout (remaining ~{remaining}s)")
            last_progress = elapsed
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval_sec, remaining))

    if payload is None:
        details = f"; last_error={last_error}" if last_error else ""
        raise RuntimeError(f"Timed out waiting for VM handshake ack at {ack_uri}{details}")

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

    print(f"VM handshake received: requested={requested_count} accepted={accepted_count}")

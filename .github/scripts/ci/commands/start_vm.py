"""Start the BMT VM so it can process the run trigger written by the trigger step."""

from __future__ import annotations

import os
import time
from typing import Any

import click

from ci.adapters import gcloud_cli


def _required_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Set {name}.")
    return value


def _instance_status(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    return str(status).strip() if status is not None else ""


def _last_start_timestamp(payload: dict[str, Any]) -> str | None:
    raw = payload.get("lastStartTimestamp")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _is_truthy(raw: str | None) -> bool:
    value = (raw or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


@click.command("start-vm")
@click.option(
    "--timeout-sec",
    default=180,
    show_default=True,
    type=int,
    help="Must match config/env_contract.json defaults.BMT_HANDSHAKE_TIMEOUT_SEC when env unset.",
)
@click.option("--poll-interval-sec", default=5, show_default=True, type=int)
@click.option(
    "--stabilization-sec",
    default=45,
    show_default=True,
    type=int,
    help="Require VM to remain RUNNING for this duration after start readiness.",
)
@click.option(
    "--allow-manual-start",
    "--allow-manual-debug-start",
    is_flag=True,
    help="Allow manual VM start outside GitHub Actions (debug/maintenance/testing only).",
)
def command(timeout_sec: int, poll_interval_sec: int, stabilization_sec: int, *, allow_manual_start: bool) -> None:
    """Start the BMT VM (reads GCP_PROJECT, GCP_ZONE, BMT_VM_NAME from env)."""
    in_actions = _is_truthy(os.environ.get("GITHUB_ACTIONS"))
    if not in_actions and not allow_manual_start and not _is_truthy(os.environ.get("BMT_ALLOW_MANUAL_VM_START")):
        raise click.ClickException(
            "Manual VM start is blocked by policy. Allowed purposes: debugging, maintenance, testing. "
            "Use --allow-manual-start or set BMT_ALLOW_MANUAL_VM_START=1 for explicit manual starts."
        )

    project = _required_env("GCP_PROJECT")
    zone = _required_env("GCP_ZONE")
    instance_name = _required_env("BMT_VM_NAME")
    before: dict[str, Any] | None = None
    before_status = ""
    before_last_start: str | None = None
    try:
        before = gcloud_cli.vm_describe(project, zone, instance_name)
        before_status = _instance_status(before)
        before_last_start = _last_start_timestamp(before)
    except gcloud_cli.GcloudError as exc:
        print(f"::warning::Could not describe VM before start: {exc}")
    try:
        gcloud_cli.vm_start(project, zone, instance_name)
    except gcloud_cli.GcloudError as exc:
        if "already running" in str(exc).lower():
            print(f"::warning::{exc}")
            print("VM already running; continuing readiness checks.")
        else:
            print(f"::error::{exc}")
            raise
    print(f"Start command submitted for VM {instance_name} (zone={zone})")
    print(
        f"Waiting for RUNNING state (timeout={timeout_sec}s, poll={poll_interval_sec}s); "
        f"previous status={before_status or '<unknown>'} previous lastStart={before_last_start or '<none>'}"
    )

    deadline = time.monotonic() + timeout_sec
    last_seen_status = ""
    last_seen_start: str | None = None
    while time.monotonic() < deadline:
        describe = gcloud_cli.vm_describe(project, zone, instance_name)
        last_seen_status = _instance_status(describe)
        last_seen_start = _last_start_timestamp(describe)
        running = last_seen_status == "RUNNING"
        start_advanced = before_last_start is None or (
            last_seen_start is not None and last_seen_start != before_last_start
        )
        already_running = before_status == "RUNNING" and running
        if running and (start_advanced or already_running):
            print(
                f"VM ready: status={last_seen_status} lastStartTimestamp={last_seen_start or '<none>'} "
                f"(previous={before_last_start or '<none>'})"
            )
            if stabilization_sec <= 0:
                return
            print(f"Stabilizing RUNNING state for {stabilization_sec}s (poll={poll_interval_sec}s)")
            stable_deadline = time.monotonic() + stabilization_sec
            while time.monotonic() < stable_deadline:
                stable_describe = gcloud_cli.vm_describe(project, zone, instance_name)
                stable_status = _instance_status(stable_describe)
                if stable_status != "RUNNING":
                    raise click.ClickException(
                        f"VM became unstable during stabilization window; status={stable_status or '<unknown>'}"
                    )
                remaining = stable_deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(max(1, poll_interval_sec), remaining))
            print("VM stabilization passed.")
            return
        time.sleep(max(1, poll_interval_sec))

    message = (
        "VM did not reach ready state after start command; "
        f"last status={last_seen_status or '<unknown>'} "
        f"lastStartTimestamp={last_seen_start or '<none>'} "
        f"previousLastStart={before_last_start or '<none>'}"
    )
    raise click.ClickException(message)

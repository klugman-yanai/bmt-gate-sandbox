#!/usr/bin/env python3
"""Live BMT Monitor — TUI dashboard for workflow/VM/GCS/status polling."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Reuse existing helpers for GCS polling
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".github" / "scripts"))
from ci.config import resolve_results_prefix


@dataclass
class LegState:
    """State for a single BMT leg."""

    project: str
    bmt_id: str
    run_id: str
    status: str = "pending"  # pending, running, pass, fail, error
    score: str | None = None
    duration: str | None = None
    verdict_data: dict[str, Any] | None = None
    verdict_detected_at: str | None = None  # When verdict file first appeared


@dataclass
class MonitorState:
    """All polled state for the monitor."""

    run_id: str
    repository: str
    bucket: str
    vm_name: str
    zone: str
    config_root: Path
    auto_follow: bool = False  # If True, continuously detect new runs

    # Workflow
    workflow_status: str | None = None
    workflow_conclusion: str | None = None
    workflow_branch: str | None = None
    workflow_sha: str | None = None
    workflow_created_at: str | None = None
    workflow_duration: str | None = None
    jobs: list[dict[str, Any]] = field(default_factory=list)

    # VM
    vm_state: str | None = None  # RUNNING, TERMINATED, STAGING, etc.

    # GCS trigger & handshake
    trigger_data: dict[str, Any] | None = None
    handshake_data: dict[str, Any] | None = None
    trigger_timestamp: str | None = None
    handshake_timestamp: str | None = None

    # Legs
    legs: list[LegState] = field(default_factory=list)
    legs_completed: int = 0
    legs_total: int = 0

    # Commit status
    commit_status_state: str | None = None
    commit_status_description: str | None = None

    # Meta
    last_poll: str | None = None
    error: str | None = None
    new_run_detected: str | None = None  # Message when switching to new run


def run_json_cmd(cmd: list[str]) -> dict[str, Any] | list[Any] | None:
    """Run command that outputs JSON; return parsed data or None on error."""
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def run_text_cmd(cmd: list[str]) -> str | None:
    """Run command that outputs text; return stdout or None on error."""
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def poll_workflow(run_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Poll workflow status and jobs. Returns (workflow_data, jobs_list)."""
    data = run_json_cmd(
        [
            "gh",
            "run",
            "view",
            run_id,
            "--json",
            "status,conclusion,jobs,headSha,headBranch,createdAt,updatedAt",
        ]
    )
    if not data or not isinstance(data, dict):
        return None, []

    jobs_raw = data.get("jobs", [])
    jobs = jobs_raw if isinstance(jobs_raw, list) else []
    return data, jobs


def poll_vm_state(vm_name: str, zone: str) -> str | None:
    """Poll VM state. Returns RUNNING, TERMINATED, STAGING, etc., or None."""
    data = run_json_cmd(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            "--zone",
            zone,
            "--format=json",
        ]
    )
    if not data or not isinstance(data, dict):
        return None
    return data.get("status")


def poll_gcs_json(uri: str) -> dict[str, Any] | None:
    """Download a GCS object as JSON; return parsed data or None."""
    text = run_text_cmd(["gcloud", "storage", "cat", uri])
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def poll_commit_status(repo: str, sha: str) -> tuple[str | None, str | None]:
    """Poll commit status. Returns (state, description) or (None, None)."""
    data = run_json_cmd(["gh", "api", f"repos/{repo}/commits/{sha}/status"])
    if not data or not isinstance(data, dict):
        return None, None

    state = data.get("state")
    statuses = data.get("statuses", [])
    if isinstance(statuses, list) and statuses:
        # Find BMT Gate status
        for status_obj in statuses:
            if isinstance(status_obj, dict) and "BMT" in status_obj.get("context", ""):
                return status_obj.get("state"), status_obj.get("description")
    return state, None


def format_duration(start_iso: str | None, end_iso: str | None = None) -> str:
    """Format duration from ISO timestamps."""
    if not start_iso:
        return "—"
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00")) if end_iso else datetime.now(timezone.utc)
        delta = int((end - start).total_seconds())
        mins, secs = divmod(delta, 60)
        return f"{mins:02d}:{secs:02d}"
    except (ValueError, AttributeError):
        return "—"


def poll_all(state: MonitorState) -> None:
    """Poll all data sources and update state."""
    try:
        # Auto-follow: check for new runs
        if state.auto_follow:
            new_run_id = auto_detect_run_id()
            if new_run_id and new_run_id != state.run_id:
                # Switch to new run
                old_run_id = state.run_id
                state.run_id = new_run_id
                if old_run_id == "waiting":
                    state.new_run_detected = f"Detected new run: {new_run_id}"
                else:
                    state.new_run_detected = f"Switched from run {old_run_id} to {new_run_id}"
                # Reset state for new run
                state.workflow_status = None
                state.workflow_conclusion = None
                state.workflow_branch = None
                state.workflow_sha = None
                state.workflow_created_at = None
                state.workflow_duration = None
                state.jobs = []
                state.trigger_data = None
                state.handshake_data = None
                state.legs = []
                state.commit_status_state = None
                state.commit_status_description = None
            else:
                # Clear notification after a few polls
                state.new_run_detected = None

        # If still waiting for a run, skip polling
        if state.run_id == "waiting":
            state.last_poll = datetime.now(timezone.utc).strftime("%H:%M:%S")
            return

        # Workflow
        wf_data, jobs = poll_workflow(state.run_id)
        if wf_data:
            state.workflow_status = wf_data.get("status")
            state.workflow_conclusion = wf_data.get("conclusion")
            state.workflow_branch = wf_data.get("headBranch")
            state.workflow_sha = wf_data.get("headSha")
            state.workflow_created_at = wf_data.get("createdAt")
            state.workflow_duration = format_duration(wf_data.get("createdAt"), wf_data.get("updatedAt"))
            state.jobs = jobs

        # VM
        state.vm_state = poll_vm_state(state.vm_name, state.zone)

        # GCS trigger
        trigger_uri = f"gs://{state.bucket}/triggers/runs/{state.run_id}.json"
        trigger_data = poll_gcs_json(trigger_uri)
        if trigger_data:
            state.trigger_data = trigger_data
            # Capture trigger timestamp if available
            if not state.trigger_timestamp and "triggered_at" in trigger_data:
                state.trigger_timestamp = trigger_data["triggered_at"]

            # Initialize legs from trigger if not already set
            if not state.legs and "legs" in trigger_data and isinstance(trigger_data["legs"], list):
                state.legs = [
                    LegState(
                        project=leg["project"],
                        bmt_id=leg["bmt_id"],
                        run_id=leg["run_id"],
                    )
                    for leg in trigger_data["legs"]
                    if isinstance(leg, dict)
                ]
                state.legs_total = len(state.legs)

        # GCS handshake
        handshake_uri = f"gs://{state.bucket}/triggers/acks/{state.run_id}.json"
        handshake_data = poll_gcs_json(handshake_uri)
        if handshake_data:
            state.handshake_data = handshake_data
            # Capture handshake timestamp if not already captured
            if not state.handshake_timestamp and "acknowledged_at" in handshake_data:
                state.handshake_timestamp = handshake_data["acknowledged_at"]

        # Per-leg verdicts
        completed = 0
        for leg in state.legs:
            try:
                results_prefix = resolve_results_prefix(state.config_root, leg.project, leg.bmt_id)
                verdict_uri = f"gs://{state.bucket}/{results_prefix}/snapshots/{leg.run_id}/ci_verdict.json"
                verdict = poll_gcs_json(verdict_uri)
                if verdict:
                    # Mark when verdict was first detected
                    if not leg.verdict_detected_at:
                        leg.verdict_detected_at = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    leg.verdict_data = verdict
                    leg.status = verdict.get("status", "unknown")
                    leg.score = str(verdict.get("current_score")) if verdict.get("current_score") else None
                    completed += 1
            except Exception:  # noqa: S110, PERF203
                pass  # Gracefully skip legs with missing config or GCS files
        state.legs_completed = completed

        # Commit status (if we have sha)
        if state.workflow_sha:
            cs_state, cs_desc = poll_commit_status(state.repository, state.workflow_sha)
            state.commit_status_state = cs_state
            state.commit_status_description = cs_desc

        state.last_poll = datetime.now(timezone.utc).strftime("%H:%M:%S")
        state.error = None

    except Exception as exc:
        state.error = f"Poll error: {exc}"


def render_header(state: MonitorState) -> Panel:
    """Render workflow header panel."""
    lines = []
    lines.append(f"Repository: {state.repository}")
    if state.run_id == "waiting":
        lines.append("[yellow]Waiting for workflow run on current branch...[/yellow]")
        lines.append("(Will auto-detect when a new run starts)")
    else:
        lines.append(
            f"Workflow: #{state.run_id}  Branch: {state.workflow_branch or '?'}  SHA: {state.workflow_sha or '?'}"
        )
        lines.append(f"Status: {state.workflow_status or '?'}  Duration: {state.workflow_duration or '—'}")
    return Panel("\n".join(lines), title="BMT Live Monitor", border_style="cyan")


def render_pipeline(state: MonitorState) -> Panel:
    """Render pipeline jobs panel."""
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Status", style="bold")
    table.add_column("Job")
    table.add_column("Duration")
    table.add_column("Detail")

    for job in state.jobs:
        name = job.get("name", "")
        status = job.get("status", "")
        conclusion = job.get("conclusion", "")
        started_at = job.get("startedAt")
        completed_at = job.get("completedAt")

        # Status icon
        if conclusion == "success":
            icon = "✓"
            style = "green"
        elif conclusion in ("failure", "cancelled"):
            icon = "✗"
            style = "red"
        elif status == "in_progress":
            icon = "●"
            style = "yellow"
        else:
            icon = "◌"
            style = "dim"

        duration = format_duration(started_at, completed_at) if started_at else "—"
        detail = conclusion or status or "queued"

        table.add_row(
            Text(icon, style=style),
            name,
            duration,
            detail,
        )

    return Panel(table, title="Pipeline", border_style="blue")


def render_vm(state: MonitorState) -> Panel:
    """Render VM state and execution progress panel."""
    lines = []
    vm_style = "green" if state.vm_state == "RUNNING" else "dim"
    lines.append(
        f"State: [{vm_style}]{state.vm_state or '?'}[/{vm_style}]   Name: {state.vm_name}   Zone: {state.zone}"
    )

    # Execution pipeline stages
    lines.append("")
    lines.append("Execution Pipeline:")

    # Stage 1: Trigger
    if state.trigger_data:
        trigger_time = state.trigger_timestamp or "?"
        lines.append(f"  ✓ Trigger written at {trigger_time}")
    else:
        lines.append("  ◌ Waiting for trigger...")

    # Stage 2: Handshake
    if state.handshake_data:
        ack_time = state.handshake_timestamp or state.handshake_data.get("acknowledged_at", "?")
        leg_count = len(state.handshake_data.get("legs", []))
        # Calculate time from trigger to handshake
        if state.trigger_timestamp and state.handshake_timestamp:
            try:
                t1 = datetime.fromisoformat(state.trigger_timestamp.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(state.handshake_timestamp.replace("Z", "+00:00"))
                delta = int((t2 - t1).total_seconds())
                lines.append(f"  ✓ VM acknowledged at {ack_time} ({delta}s pickup time, {leg_count} legs)")
            except (ValueError, AttributeError):
                lines.append(f"  ✓ VM acknowledged at {ack_time} ({leg_count} legs)")
        else:
            lines.append(f"  ✓ VM acknowledged at {ack_time} ({leg_count} legs)")
    else:
        lines.append("  ◌ Waiting for VM to pick up trigger...")

    # Stage 3: Leg execution
    if state.legs_total > 0:
        if state.legs_completed == state.legs_total:
            lines.append(f"  ✓ All legs complete ({state.legs_completed}/{state.legs_total})")
        elif state.legs_completed > 0:
            lines.append(
                f"  ● Executing legs: {state.legs_completed}/{state.legs_total} complete ([cyan]{state.legs_total - state.legs_completed} running[/cyan])"
            )
        elif state.handshake_data:
            lines.append(f"  ● Starting execution ({state.legs_total} legs queued)")
        else:
            lines.append(f"  ◌ {state.legs_total} legs pending VM pickup")

    return Panel("\n".join(lines), title="VM Execution", border_style="magenta")


def render_legs(state: MonitorState) -> Panel:
    """Render legs table panel."""
    table = Table(show_header=True, box=None)
    table.add_column("Project")
    table.add_column("BMT ID")
    table.add_column("Status")
    table.add_column("Score", justify="right")
    table.add_column("Completed", justify="right")

    for leg in state.legs:
        # Status styling
        if leg.status == "pass":
            status_text = Text("● pass", style="green")
        elif leg.status == "fail":
            status_text = Text("● fail", style="red")
        elif leg.status == "error":
            status_text = Text("● error", style="red")
        elif leg.verdict_detected_at:
            # Has verdict but status not yet determined
            status_text = Text("● complete", style="cyan")
        elif state.handshake_data:
            # VM acknowledged, so this leg is either queued or running
            status_text = Text("● running", style="yellow")
        else:
            status_text = Text("◌ pending", style="dim")

        score = leg.score or "—"
        completed_at = leg.verdict_detected_at or "—"

        table.add_row(leg.project, leg.bmt_id, status_text, score, completed_at)

    return Panel(table, title="Legs", border_style="yellow")


def render_commit_status(state: MonitorState) -> Panel:
    """Render commit status panel."""
    if state.commit_status_state:
        status_style = {
            "success": "green",
            "pending": "yellow",
            "failure": "red",
            "error": "red",
        }.get(state.commit_status_state, "dim")

        desc = state.commit_status_description or "No description"
        text = f'BMT Gate: [{status_style}]{state.commit_status_state}[/{status_style}] — "{desc}"'
    else:
        text = "BMT Gate: waiting for status..."

    return Panel(text, title="Commit Status", border_style="green")


def render_footer(state: MonitorState, interval: int) -> str:
    """Render footer text."""
    parts = []
    if state.last_poll:
        parts.append(f"Last poll: {state.last_poll}Z")
    if state.auto_follow:
        parts.append("[cyan](auto-follow enabled)[/cyan]")
    parts.append(f"(every {interval}s)")
    parts.append("Ctrl+C to exit")
    if state.new_run_detected:
        parts.append(f"[green]🔔 {state.new_run_detected}[/green]")
    if state.error:
        parts.append(f"[red]Error: {state.error}[/red]")
    return "  ".join(parts)


def render(state: MonitorState, interval: int) -> Layout:
    """Build complete layout for Live."""
    layout = Layout()
    layout.split_column(
        Layout(render_header(state), size=5),
        Layout(render_pipeline(state), size=12),
        Layout(render_vm(state), size=10),  # Expanded for execution pipeline
        Layout(render_legs(state), size=10),
        Layout(render_commit_status(state), size=3),
        Layout(Text(render_footer(state, interval)), size=1),
    )
    return layout


def auto_detect_run_id() -> str | None:
    """Auto-detect latest workflow run ID on current branch."""
    # Get current branch
    branch = run_text_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if not branch:
        return None

    # Get latest run on this branch
    data = run_json_cmd(["gh", "run", "list", "--branch", branch, "--limit", "1", "--json", "databaseId"])
    if not data or not isinstance(data, list) or not data:
        return None

    return str(data[0].get("databaseId"))


@click.command()
@click.option("--run-id", help="GitHub Actions workflow run ID")
@click.option(
    "--auto",
    is_flag=True,
    help="Auto-detect and follow latest run on current branch (continuously checks for new runs)",
)
@click.option(
    "--prod",
    is_flag=True,
    help="Use production repo (Kardome-org/core-main) instead of test (klugman-yanai/bmt-gate-sandbox)",
)
@click.option(
    "--repo",
    help="Override repository (format: owner/repo). Overrides --prod flag.",
)
@click.option(
    "--bucket",
    envvar="GCS_BUCKET",
    default="train-kws-202311-bmt-gate",
    help="GCS bucket name (default: train-kws-202311-bmt-gate)",
)
@click.option(
    "--vm-name",
    envvar="BMT_VM_NAME",
    default="bmt-performance-gate",
    help="VM instance name (default: bmt-performance-gate)",
)
@click.option(
    "--zone",
    envvar="GCP_ZONE",
    default="europe-west4-a",
    help="GCP zone (default: europe-west4-a)",
)
@click.option("--config-root", default="remote", help="Config root (default: remote)")
@click.option("--interval", default=5, type=int, help="Poll interval in seconds")
def main(
    run_id: str | None,
    auto: bool,
    prod: bool,
    repo: str | None,
    bucket: str,
    vm_name: str,
    zone: str,
    config_root: str,
    interval: int,
) -> None:
    """Live BMT Monitor — TUI dashboard for workflow/VM/GCS/status polling."""
    # Determine repository
    if repo:
        repository = repo
    elif prod:
        repository = "Kardome-org/core-main"
    else:
        repository = "klugman-yanai/bmt-gate-sandbox"

    if auto:
        detected = auto_detect_run_id()
        if detected:
            run_id = detected
            click.echo(f"Auto-detected run ID: {run_id} (repo: {repository})")
        else:
            # Start with a placeholder; will detect on first poll
            run_id = "waiting"
            click.echo(f"Waiting for workflow run on current branch... (repo: {repository})")
    elif not run_id:
        click.echo("Error: --run-id or --auto is required", err=True)
        sys.exit(1)

    config_path = Path(config_root).resolve()
    if not config_path.is_dir():
        click.echo(f"Error: Config root not found: {config_path}", err=True)
        sys.exit(1)

    state = MonitorState(
        run_id=run_id,
        repository=repository,
        bucket=bucket,
        vm_name=vm_name,
        zone=zone,
        config_root=config_path,
        auto_follow=auto,
    )

    console = Console()

    try:
        with Live(render(state, interval), console=console, refresh_per_second=1) as live:
            while True:
                poll_all(state)
                live.update(render(state, interval))
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped.[/yellow]")


if __name__ == "__main__":
    main()

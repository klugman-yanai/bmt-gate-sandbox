"""BMT execution and monitoring."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def monitor() -> None:
    """Live TUI: trigger, ack, status, VM/GCS state."""
    from tools.bmt.bmt_monitor import BmtMonitor

    raise typer.Exit(BmtMonitor().run())


@app.command("add-project")
def add_project(
    project: Annotated[
        str,
        typer.Argument(help="Project name (lowercase, e.g. myproject)"),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print paths only, don't write"),
    ] = False,
) -> None:
    """Scaffold a new BMT project under gcp/image/projects/."""
    from tools.scripts.add_bmt_project import add_project as add_project_impl

    raise typer.Exit(add_project_impl(project, dry_run=dry_run))


@app.command("symlink-deps")
def symlink_deps(
    bmt_root: Annotated[
        Path | None,
        typer.Option("--bmt-root", help="BMT root dir; default from BMT_ROOT env or repo default"),
    ] = None,
    deps_dir: Annotated[
        Path | None,
        typer.Option("--deps-dir", help="Override shared deps directory"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print what would be done"),
    ] = False,
) -> None:
    """Symlink shared BMT native deps into each project's runner lib directory."""
    from tools.scripts.symlink_bmt_deps import run as symlink_deps_run

    rc = symlink_deps_run(bmt_root=bmt_root, deps_dir=deps_dir, dry_run=dry_run)
    raise typer.Exit(rc)


@app.command()
def wait(
    manifest: Annotated[
        str,
        typer.Option("--manifest", help="JSON manifest from trigger step"),
    ] = ...,
    timeout_sec: Annotated[
        int,
        typer.Option("--timeout-sec", help="Timeout in seconds"),
    ] = ...,
    poll_interval_sec: Annotated[
        int,
        typer.Option("--poll-interval-sec", help="Poll interval in seconds"),
    ] = 30,
) -> None:
    """Poll GCS for verdicts and aggregate results (local/manual)."""
    from tools.bmt.bmt_wait_verdicts import STATUS_PASS, run as wait_run

    args = SimpleNamespace(
        manifest=manifest,
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
    )
    decision = wait_run(args)
    raise typer.Exit(0 if decision == STATUS_PASS else 1)


@app.command("vm-check")
def vm_check(
    run_id: Annotated[
        str,
        typer.Argument(help="Workflow run ID (e.g. from trigger step)"),
    ],
    bucket: Annotated[
        str | None,
        typer.Option("--bucket", help="GCS bucket; default from GCS_BUCKET"),
    ] = None,
) -> None:
    """Fetch trigger and handshake ack JSON from GCS for a run (requires GCS_BUCKET)."""
    from tools.bmt.vm_check import run as vm_check_run

    raise typer.Exit(vm_check_run(run_id, bucket=bucket))

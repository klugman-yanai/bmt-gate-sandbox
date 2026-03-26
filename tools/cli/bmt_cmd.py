"""BMT execution and monitoring."""
from __future__ import annotations

import sys
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
    """Scaffold a new BMT project under backend/projects/."""
    sys.argv = ["add_bmt_project", project] + (["--dry-run"] if dry_run else [])
    from tools.scripts.add_bmt_project import main

    raise typer.Exit(main())

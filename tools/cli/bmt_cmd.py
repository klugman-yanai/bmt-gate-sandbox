"""BMT project scaffolding and publishing."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True)


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
    """Scaffold a new staged BMT project under gcp/stage/projects/."""
    from tools.bmt.scaffold import add_project as add_project_impl

    raise typer.Exit(add_project_impl(project, dry_run=dry_run))


@app.command("add-bmt")
def add_bmt(
    project: Annotated[
        str,
        typer.Argument(help="Project name (lowercase, e.g. myproject)"),
    ],
    bmt_slug: Annotated[
        str,
        typer.Argument(help="BMT slug (lowercase, e.g. false_rejects)"),
    ],
) -> None:
    """Scaffold a new BMT manifest under gcp/stage/projects/<project>/bmts/."""
    from tools.bmt.scaffold import add_bmt as add_bmt_impl

    raise typer.Exit(add_bmt_impl(project, bmt_slug))


@app.command("publish-bmt")
def publish_bmt(
    project: Annotated[
        str,
        typer.Argument(help="Project name"),
    ],
    bmt_slug: Annotated[
        str,
        typer.Argument(help="BMT slug"),
    ],
    no_sync: Annotated[
        bool,
        typer.Option("--no-sync", help="Only publish locally; skip syncing the project subtree to GCS"),
    ] = False,
) -> None:
    """Validate locally, publish an immutable plugin bundle, and sync to GCS."""
    from tools.bmt.publisher import publish_bmt as publish_bmt_impl

    result = publish_bmt_impl(project=project, bmt_slug=bmt_slug, sync=not no_sync)
    typer.echo(result.plugin_ref)
    raise typer.Exit(0)


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

"""BMT project scaffolding and publishing."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True)

stage = typer.Typer(
    name="stage",
    help="One entry point for staged projects: create a project, add a BMT, publish plugin bundles.",
    no_args_is_help=True,
)


@stage.command("project")
def stage_project(
    project: Annotated[
        str,
        typer.Argument(
            help="Project name: lowercase letters, digits, underscores; start with a letter (e.g. myproject). "
            "Becomes the folder under gcp/stage/projects/."
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print paths only, don't write"),
    ] = False,
) -> None:
    """Create gcp/stage/projects/<project>/ (plugin workspace + default example BMT)."""
    from tools.bmt.scaffold import add_project as add_project_impl

    raise typer.Exit(add_project_impl(project, dry_run=dry_run))


@stage.command("bmt")
def stage_bmt(
    project: Annotated[
        str,
        typer.Argument(help="Existing project name (same rules as `stage project`, e.g. myproject)."),
    ],
    benchmark: Annotated[
        str,
        typer.Argument(
            help="Benchmark folder name (same character rules as the project, e.g. false_rejects). "
            "Creates bmts/<benchmark>/bmt.json; the manifest field is still bmt_slug."
        ),
    ],
) -> None:
    """Add gcp/stage/projects/<project>/bmts/<benchmark>/bmt.json (disabled manifest)."""
    from tools.bmt.scaffold import add_bmt as add_bmt_impl

    raise typer.Exit(add_bmt_impl(project, benchmark))


@stage.command("publish")
def stage_publish(
    project: Annotated[
        str,
        typer.Argument(help="Project name."),
    ],
    benchmark: Annotated[
        str,
        typer.Argument(help="Benchmark folder name (the segment under bmts/; must match that folder)."),
    ],
    no_sync: Annotated[
        bool,
        typer.Option("--no-sync", help="Only publish locally; skip syncing the project subtree to GCS"),
    ] = False,
    no_enable: Annotated[
        bool,
        typer.Option("--no-enable", help="Leave enabled unchanged in bmt.json (default: set enabled true)"),
    ] = False,
) -> None:
    """Validate, build an immutable plugin bundle for this BMT, and sync to GCS (unless --no-sync)."""
    from tools.bmt.publisher import publish_bmt as publish_bmt_impl

    result = publish_bmt_impl(
        project=project,
        bmt_slug=benchmark,
        sync=not no_sync,
        enable=not no_enable,
    )
    typer.echo(result.plugin_ref)
    raise typer.Exit(0)


app.add_typer(stage, name="stage")


@app.command("verify")
def bmt_verify(
    project: Annotated[str, typer.Argument(help="Staged project name (gcp/stage/projects/<name>/).")],
    benchmark: Annotated[
        str,
        typer.Argument(help="BMT folder under bmts/ (must match bmt_slug in bmt.json)."),
    ],
) -> None:
    """Load workspace plugin + manifests locally (no GCS). Use before ``tools publish``."""
    from tools.bmt.publisher import validate_workspace_plugin
    from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root

    root = repo_root() / DEFAULT_STAGE_ROOT
    validate_workspace_plugin(stage_root=root, project=project, bmt_slug=benchmark)
    typer.echo(f"OK — workspace plugin for {project}/{benchmark} loads.")
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

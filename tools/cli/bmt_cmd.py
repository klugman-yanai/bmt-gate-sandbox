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
            "Becomes the folder under benchmarks/projects/."
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print paths only, don't write"),
    ] = False,
) -> None:
    """Create benchmarks/projects/<project>/ (plugin workspace + default example BMT)."""
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
    """Add benchmarks/projects/<project>/bmts/<benchmark>/bmt.json (disabled manifest)."""
    from tools.bmt.scaffold import add_bmt as add_bmt_impl

    raise typer.Exit(add_bmt_impl(project, benchmark))


@stage.command("manifest-template")
def stage_manifest_template(
    project: Annotated[str, typer.Argument(help="Staged project name.")],
    benchmark: Annotated[
        str,
        typer.Argument(help="Benchmark folder name under bmts/ (must match bmt_slug in the JSON)."),
    ],
    plugin_ref: Annotated[
        str,
        typer.Option("--plugin-ref", help="Value for the plugin_ref field (default workspace:default)."),
    ] = "workspace:default",
    stdout: Annotated[
        bool,
        typer.Option("--stdout", help="Print JSON to stdout instead of writing a file."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Allow overwriting an existing bmt.json."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print target path only; do not write."),
    ] = False,
) -> None:
    """Emit a default bmt.json from the shared Pydantic factory (opt-in; see docs/bmt-python-contributor-protocol.md §3)."""
    from backend.runtime.sdk.manifest_build import build_default_bmt_manifest
    from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root

    manifest = build_default_bmt_manifest(project, benchmark, plugin_ref=plugin_ref)
    text = manifest.model_dump_json(by_alias=True, indent=2) + "\n"
    root = repo_root() / DEFAULT_STAGE_ROOT
    path = root / "projects" / project / "bmts" / benchmark / "bmt.json"
    if stdout:
        typer.echo(text, nl=False)
        raise typer.Exit(0)
    if dry_run:
        typer.echo(str(path))
        raise typer.Exit(0)
    if path.exists() and not force:
        typer.echo(f"Refusing to overwrite {path} (use --force)", err=True)
        raise typer.Exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    typer.echo(f"Wrote {path}")
    raise typer.Exit(0)


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


@stage.command("publish-plugin")
def stage_publish_plugin(
    project: Annotated[str, typer.Argument(help="Project name.")],
    plugin_name: Annotated[str, typer.Argument(help="Plugin name (e.g. default).")],
    no_sync: Annotated[
        bool,
        typer.Option("--no-sync", help="Skip syncing the project subtree to GCS after publish."),
    ] = False,
) -> None:
    """Publish workspace plugin once and update plugin_ref on every BMT that uses this plugin."""
    from tools.bmt.publisher import publish_plugin_for_project

    result = publish_plugin_for_project(project=project, plugin_name=plugin_name, sync=not no_sync)
    typer.echo(result.plugin_ref)
    raise typer.Exit(0)


@stage.command("doctor")
def stage_doctor(
    project: Annotated[str, typer.Argument(help="Staged project name (benchmarks/projects/<name>/).")],
) -> None:
    """Validate manifests, paths, published digests, and workspace loads for one project."""
    from tools.bmt.stage_doctor import doctor_stage_project
    from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root

    root = repo_root() / DEFAULT_STAGE_ROOT
    code, lines = doctor_stage_project(stage_root=root, project=project)
    for line in lines:
        typer.echo(line)
    raise typer.Exit(code)


app.add_typer(stage, name="stage")


@app.command("verify")
def bmt_verify(
    project: Annotated[str, typer.Argument(help="Staged project name (benchmarks/projects/<name>/).")],
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

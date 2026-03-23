"""Unified entry for Pulumi apply, repo vars check, bucket preflight/deploy, E2E preflight."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from tools.repo.just_image_gate import evaluate_image_skip, run_just_image
from tools.repo.paths import repo_root

app = typer.Typer(
    name="workspace",
    help="Pulumi, GitHub repo vars, GCS bucket preflight/deploy, E2E readiness (one namespace).",
    no_args_is_help=True,
)


def _run_tools(argv: list[str]) -> int:
    return subprocess.run(
        [sys.executable, "-m", "tools", *argv],
        cwd=repo_root(),
        check=False,
    ).returncode


@app.command("pulumi")
def workspace_pulumi(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose Pulumi/preflight output."),
    ] = False,
) -> None:
    """Pulumi preflight + apply + push GitHub repo vars (`tools pulumi apply`)."""
    args = ["pulumi", "apply"]
    if verbose:
        args.append("--verbose")
    raise typer.Exit(_run_tools(args))


@app.command("validate")
def workspace_validate() -> None:
    """Compare GitHub repo variables to Pulumi contract (`tools repo validate`)."""
    raise typer.Exit(_run_tools(["repo", "validate"]))


@app.command("preflight")
def workspace_preflight(
    snapshot: Annotated[
        Path | None,
        typer.Option(
            "--snapshot",
            "--report",
            help="Replay diff from a saved JSON snapshot (--report is an alias).",
        ),
    ] = None,
    local_only: Annotated[
        bool,
        typer.Option("--local-only", help="Only list gcp/image, no GCS."),
    ] = False,
    with_image: Annotated[
        bool,
        typer.Option(
            "--with-image",
            help="After bucket checks, run `just image` when git + Artifact Registry do not auto-skip "
            "(ignored with --local-only or --snapshot).",
        ),
    ] = False,
    force_image: Annotated[
        bool,
        typer.Option(
            "--force-image",
            help="Always run `just image` after bucket checks (implies --with-image; same semantics as "
            "`just ship --force-image`; ignored with --local-only or --snapshot).",
        ),
    ] = False,
) -> None:
    """GCS vs gcp/image diff + core-main workflow drift (`tools bucket preflight`)."""
    args: list[str] = ["bucket", "preflight"]
    if snapshot is not None:
        args.extend(["--snapshot", str(snapshot)])
    if local_only:
        args.append("--local-only")
    rc = _run_tools(args)
    if rc != 0:
        raise typer.Exit(rc)

    consider_image = (with_image or force_image) and snapshot is None and not local_only
    if not consider_image:
        raise typer.Exit(0)

    root_s = str(repo_root())
    skip_image, auto_note = evaluate_image_skip(
        root=root_s,
        skip_image=False,
        force_image=force_image,
        dry_run=False,
    )
    if auto_note:
        console = Console(highlight=False, soft_wrap=True)
        console.print()
        console.print(Panel(Text.from_markup(auto_note), border_style="dim", box=box.HEAVY))
        console.print()
    if skip_image:
        raise typer.Exit(0)

    img_rc = run_just_image()
    raise typer.Exit(img_rc)


@app.command("deploy")
def workspace_deploy() -> None:
    """Sync gcp/stage runtime seed to GCS and verify (`tools bucket deploy`)."""
    raise typer.Exit(_run_tools(["bucket", "deploy"]))


@app.command("e2e")
def workspace_e2e(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show planned stages only."),
    ] = False,
    skip_bucket: Annotated[
        bool,
        typer.Option("--skip-bucket", help="Skip bucket preflight (offline)."),
    ] = False,
    with_tests: Annotated[
        bool,
        typer.Option("--with-tests", help="Then run full just test."),
    ] = False,
) -> None:
    """Actions/handoff readiness checks (`tools e2e-preflight`)."""
    from tools.repo.e2e_preflight import run_e2e_preflight

    raise typer.Exit(
        run_e2e_preflight(
            skip_bucket=skip_bucket,
            with_tests=with_tests,
            dry_run=dry_run,
        )
    )


def register_workspace(target: typer.Typer) -> None:
    target.add_typer(
        app,
        name="workspace",
        help="Pulumi, repo vars, bucket sync, E2E preflight",
        rich_help_panel="Workspace & infra",
    )

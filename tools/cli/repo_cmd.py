"""Repository validation and environment."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Annotated

import typer

from tools.repo.paths import repo_root
from tools.shared.rich_minimal import step, step_console, success_panel

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")


@app.command()
def validate() -> None:
    """Check repo vars against Pulumi outputs and the repo contract."""
    from tools.repo.gh_repo_vars import GhRepoVars

    rc = GhRepoVars().run()
    raise typer.Exit(rc)


@app.command("show-env")
def show_env() -> None:
    """Print env var names used by CI, Cloud Run, and tooling."""
    from tools.repo.gh_show_env import GhShowEnv

    raise typer.Exit(GhShowEnv().run())


@app.command("validate-layout")
def validate_layout() -> None:
    """Run [bold]gcp/[/bold] and repo layout policies (same as [bold]just test[/bold] layout checks)."""
    from tools.repo.gcp_layout_policy import GcpLayoutPolicy
    from tools.repo.repo_layout_policy import RepoLayoutPolicy

    console = step_console()
    if console is not None:
        console.print("[bold]Validate layout[/]")
    for label, runner in [("GCP layout", GcpLayoutPolicy()), ("Repo layout", RepoLayoutPolicy())]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = runner.run()
        if rc != 0:
            sys.stderr.write(buf.getvalue())
            step(console, label, ok=False)
            raise typer.Exit(rc)
        step(console, label, ok=True)
    success_panel(console, "Validate layout", "GCP and repo layout checks passed.")
    raise typer.Exit(0)


@app.command("core-main-workflows")
def core_main_workflows(
    path: Annotated[
        Path | None,
        typer.Option("--path", help="Directory of workflow YAML (default: .github/workflows)."),
    ] = None,
    mode: Annotated[
        str,
        typer.Option("--mode", help="'preflight' or 'release' (wording for missing gh only)."),
    ] = "preflight",
) -> None:
    """Compare local workflows to Kardome-org/core-main on branch ``dev`` (informational unless CORE_MAIN_WORKFLOW_CHECK=strict)."""
    from tools.repo.core_main_workflows import run_drift_check

    d = path or (Path(repo_root()) / ".github" / "workflows")
    raise typer.Exit(run_drift_check(d, mode=mode))

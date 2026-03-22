"""Repository validation and environment."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

import typer

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

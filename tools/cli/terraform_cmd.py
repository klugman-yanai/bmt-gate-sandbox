"""Terraform orchestration: preflight, apply, import-topics."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from tools.repo.paths import repo_root

app = typer.Typer(no_args_is_help=True)




def _run_tool(module: str, verbose: bool = False) -> int:
    cmd = [sys.executable, "-m", module]
    if verbose:
        cmd.append("--verbose")
    return subprocess.run(cmd, check=False, cwd=repo_root()).returncode


@app.command()
def apply(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show full output"),
    ] = False,
) -> None:
    """Run terraform preflight, apply, and push repo vars."""
    for mod in ("tools.terraform.terraform_preflight", "tools.terraform.terraform_apply"):
        rc = _run_tool(mod, verbose=verbose)
        if rc != 0:
            raise typer.Exit(rc)


@app.command("import-topics")
def import_topics(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show full output"),
    ] = False,
) -> None:
    """Import existing Pub/Sub topics into Terraform state (fix 409)."""
    rc = _run_tool("tools.terraform.terraform_import_topics", verbose=verbose)
    if rc != 0:
        raise typer.Exit(rc)
    typer.echo("Topics imported. Running terraform apply...")
    for mod in ("tools.terraform.terraform_preflight", "tools.terraform.terraform_apply"):
        rc = _run_tool(mod, verbose=verbose)
        if rc != 0:
            raise typer.Exit(rc)


@app.command()
def preflight(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show full output"),
    ] = False,
) -> None:
    """Run preflight checks only (no apply)."""
    rc = _run_tool("tools.terraform.terraform_preflight", verbose=verbose)
    raise typer.Exit(rc)

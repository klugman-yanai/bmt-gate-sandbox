"""Infrastructure orchestration: preflight, apply (Pulumi)."""

from __future__ import annotations

import subprocess
import sys
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
    """Run preflight, pulumi up, and push repo vars."""
    for mod in ("tools.pulumi.pulumi_preflight", "tools.pulumi.pulumi_apply"):
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
    rc = _run_tool("tools.pulumi.pulumi_preflight", verbose=verbose)
    raise typer.Exit(rc)

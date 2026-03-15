"""Repository validation and environment."""
from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def validate() -> None:
    """Check repo vars vs Terraform/contract and VM metadata."""
    from tools.repo.gh_repo_vars import GhRepoVars
    from tools.repo.gh_validate_vm_vars import GhValidateVmVars

    rc = GhRepoVars().run()
    if rc != 0:
        raise typer.Exit(rc)
    rc = GhValidateVmVars().run()
    raise typer.Exit(rc)


@app.command("show-env")
def show_env() -> None:
    """Print env var names used by CI, VM, and tools."""
    from tools.repo.gh_show_env import GhShowEnv

    raise typer.Exit(GhShowEnv().run())

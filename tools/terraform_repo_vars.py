#!/usr/bin/env python3
"""Export Terraform outputs + contract defaults to GitHub repo variables.

Hybrid: infra-derived vars from Terraform (terraform output -raw <name>);
behavioral vars from repo_vars_contract defaults. Run from repo root.
Secrets (GCP_WIF_PROVIDER, BMT_DISPATCH_APP_ID, BMT_DISPATCH_APP_PRIVATE_KEY)
are not set here; set them manually. See infra/README.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# So that repo_vars_contract can be imported when run as tools/terraform_repo_vars.py from repo root.
_tools_dir = Path(__file__).resolve().parent
if str(_tools_dir) not in sys.path:
    sys.path.insert(0, str(_tools_dir))

import click
from click_exit import run_click_command

from repo_vars_contract import REPO_VARS_CONTRACT, TERRAFORM_OUTPUT_TO_VAR


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _terraform_dir() -> Path:
    return _repo_root() / "infra" / "terraform"


def _terraform_output_raw(name: str) -> str:
    tf_dir = _terraform_dir()
    if not tf_dir.is_dir():
        raise FileNotFoundError(f"Terraform dir not found: {tf_dir}")
    proc = subprocess.run(
        ["terraform", "output", "-raw", name],
        cwd=tf_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"terraform output -raw {name} failed: {(proc.stderr or proc.stdout or '').strip()}"
        )
    return (proc.stdout or "").strip()


def get_expected_repo_vars_from_terraform() -> dict[str, str]:
    """Return GitHub var name -> value: Terraform for infra vars, contract defaults for the rest."""
    defaults = REPO_VARS_CONTRACT.default_dict()
    var_to_tf: dict[str, str] = {v: k for k, v in TERRAFORM_OUTPUT_TO_VAR.items()}
    result: dict[str, str] = {}
    for name in REPO_VARS_CONTRACT.all_var_names():
        if name in var_to_tf:
            tf_name = var_to_tf[name]
            result[name] = _terraform_output_raw(tf_name)
        else:
            result[name] = defaults.get(name, "")
    return result


@click.command()
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Run `gh variable set` for each var (default: print key=value)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be set, do not run gh",
)
def main(apply: bool, dry_run: bool) -> int:
    """Export repo vars to GitHub (Terraform for infra, contract defaults for behavioral)."""
    try:
        vars_to_set = get_expected_repo_vars_from_terraform()
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        click.echo(f"::error::{e}", err=True)
        return 1
    if not vars_to_set:
        click.echo("No repo vars to export.", err=True)
        return 1
    if dry_run:
        for name in sorted(vars_to_set.keys()):
            click.echo(f"Would set {name}=<redacted>")
        return 0
    if not apply:
        for name, value in sorted(vars_to_set.items()):
            click.echo(f"{name}={value}")
        return 0
    for name, value in sorted(vars_to_set.items()):
        proc = subprocess.run(
            ["gh", "variable", "set", name, "--body", value],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            click.echo(f"::error::gh variable set {name} failed: {proc.stderr or proc.stdout}", err=True)
            return 1
        click.echo(f"Set {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

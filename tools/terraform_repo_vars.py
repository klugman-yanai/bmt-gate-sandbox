#!/usr/bin/env python3
"""Export Terraform outputs to GitHub repo variables.

Terraform is the source of truth for all non-secret configuration. This script
reads terraform output -json and repo-vars-mapping.json, then either prints
key=value or applies them with `gh variable set` (--apply).

Secrets (GCP_WIF_PROVIDER, BMT_DISPATCH_APP_ID, BMT_DISPATCH_APP_PRIVATE_KEY)
are never set by this script; set them manually. See infra/README.md.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click
from click_exit import run_click_command


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _terraform_dir() -> Path:
    return _repo_root() / "infra" / "terraform"


def _mapping_path() -> Path:
    return _terraform_dir() / "repo-vars-mapping.json"


def _load_mapping() -> dict:
    path = _mapping_path()
    if not path.is_file():
        raise FileNotFoundError(f"Mapping not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("repo-vars-mapping.json must be a JSON object")
    return data


def _terraform_output_json() -> dict:
    tf_dir = _terraform_dir()
    if not tf_dir.is_dir():
        raise FileNotFoundError(f"Terraform dir not found: {tf_dir}")
    proc = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=tf_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"terraform output failed: {(proc.stderr or proc.stdout or '').strip()}"
        )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"terraform output not valid JSON: {e}") from e
    if not isinstance(out, dict):
        raise RuntimeError("terraform output -json must be an object")
    return out


def _sensitive(value: dict) -> bool:
    return value.get("sensitive", False) is True


def _get_output_value(output: dict) -> str | int | None:
    val = output.get("value")
    if val is None:
        return None
    return str(val)


def get_expected_repo_vars_from_terraform() -> dict[str, str]:
    """Return GitHub var name -> value from Terraform outputs and mapping."""
    mapping = _load_mapping()
    tf_to_gh = mapping.get("terraform_output_to_gh_var")
    if not isinstance(tf_to_gh, dict):
        raise ValueError("repo-vars-mapping.json missing terraform_output_to_gh_var object")
    outputs = _terraform_output_json()
    result: dict[str, str] = {}
    for tf_key, gh_var in tf_to_gh.items():
        if tf_key not in outputs:
            continue
        out = outputs[tf_key]
        if not isinstance(out, dict):
            continue
        if _sensitive(out):
            continue
        val = _get_output_value(out)
        if val is not None:
            result[gh_var] = str(val)
    return result


@click.command()
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Run `gh variable set` for each Terraform-sourced var (default: print key=value)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be set, do not run gh",
)
def main(apply: bool, dry_run: bool) -> int:
    """Export Terraform outputs to GitHub repo variables."""
    try:
        vars_to_set = get_expected_repo_vars_from_terraform()
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        click.echo(f"::error::{e}", err=True)
        return 1
    if not vars_to_set:
        click.echo("No Terraform-sourced vars to export.", err=True)
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

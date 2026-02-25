#!/usr/bin/env python3
"""Validate required GitHub repo variables against VM metadata."""

from __future__ import annotations

import json
import os
import subprocess

import click
from shared_env_contract import list_repo_vs_vm_metadata_vars, load_env_contract


def _cmd_exists(name: str) -> bool:
    return subprocess.run(["which", name], capture_output=True, check=False).returncode == 0


def _run_text(cmd: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _gh_var(name: str) -> str:
    rc, out, _err = _run_text(["gh", "variable", "get", name])
    return out if rc == 0 else ""


def _resolve_required(name: str, cli_value: str | None, cli_flag: str) -> str:
    value = (cli_value or "").strip() or (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Set {name} or pass {cli_flag}.")
    return value


def _normalize(name: str, value: str) -> str:
    raw = (value or "").strip()
    if name == "BMT_BUCKET_PREFIX":
        return raw.strip("/")
    return raw


def _read_vm_metadata(project: str, zone: str, vm_name: str, key: str) -> str:
    rc, out, _err = _run_text(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            "--zone",
            zone,
            "--project",
            project,
            "--format",
            f"get(metadata.items.{key})",
        ]
    )
    return out if rc == 0 else ""


def _render(value: str) -> str:
    return value or "<empty>"


@click.command()
@click.option("--vm-name", default=None, help="VM name (default: env BMT_VM_NAME)")
@click.option("--zone", default=None, help="GCP zone (default: env GCP_ZONE)")
@click.option("--project", default=None, help="GCP project (default: env GCP_PROJECT)")
@click.option("--contract", default=None, help="Path to env contract JSON (default: config/env_contract.json)")
def main(vm_name: str | None, zone: str | None, project: str | None, contract: str | None) -> None:
    """Validate repo vars vs VM metadata based on contract consistency checks."""
    if not _cmd_exists("gh"):
        click.echo("::error::gh CLI not found", err=True)
        raise click.exceptions.Exit(2)
    if not _cmd_exists("gcloud"):
        click.echo("::error::gcloud CLI not found", err=True)
        raise click.exceptions.Exit(2)

    try:
        resolved_vm = _resolve_required("BMT_VM_NAME", vm_name, "--vm-name")
        resolved_zone = _resolve_required("GCP_ZONE", zone, "--zone")
        resolved_project = _resolve_required("GCP_PROJECT", project, "--project")
    except RuntimeError as exc:
        click.echo(f"::error::{exc}", err=True)
        raise click.exceptions.Exit(2) from exc

    click.echo(f"Target VM: {resolved_vm}  zone={resolved_zone}  project={resolved_project}")
    click.echo("")
    click.echo("Comparing GitHub repo variables vs VM metadata:")

    try:
        env_contract = load_env_contract(contract)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        click.echo(f"::error::Failed to load env contract: {exc}", err=True)
        raise click.exceptions.Exit(2) from exc
    keys = list_repo_vs_vm_metadata_vars(env_contract)
    if not keys:
        click.echo("::error::No repo_vs_vm_metadata keys defined in env contract.", err=True)
        raise click.exceptions.Exit(2)

    mismatches: list[str] = []
    for key in keys:
        repo_raw = _gh_var(key)
        vm_raw = _read_vm_metadata(resolved_project, resolved_zone, resolved_vm, key)
        repo_norm = _normalize(key, repo_raw)
        vm_norm = _normalize(key, vm_raw)

        status = "OK" if repo_norm == vm_norm else "MISMATCH"
        click.echo(f"- {key}: {status}")
        click.echo(f"  repo: {_render(repo_raw)}")
        click.echo(f"  vm  : {_render(vm_raw)}")
        if repo_norm != vm_norm:
            mismatches.append(key)

    if mismatches:
        click.echo("")
        click.echo(f"::error::Mismatch detected for: {', '.join(mismatches)}", err=True)
        click.echo(
            "::error::Update repo vars and resync VM metadata (workflow sync-vm-metadata or setup_vm_startup.sh).",
            err=True,
        )
        raise click.exceptions.Exit(1)

    click.echo("")
    click.echo("::notice::Repo vars and VM metadata match for required vars.")


if __name__ == "__main__":
    main()

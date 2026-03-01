#!/usr/bin/env python3
"""Validate code/runtime bucket contract for manual sync deployments.

Paths such as sk/results/false_rejects and runner URIs are project-specific
(current sk project); derive from bmt_projects.json + jobs config where possible.
CLI and contract allow overrides.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from shared_bucket_env import (
    bucket_option,
    code_bucket_root_uri,
    runtime_bucket_root_uri,
)

REQUIRED_CODE = [
    "root_orchestrator.py",
    "bmt_projects.json",
    "pyproject.toml",
    "sk/bmt_manager.py",
    "sk/config/bmt_jobs.json",
    "sk/config/input_template.json",
    "uv.lock",
    "_tools/uv/linux-x86_64/uv",
    "_tools/uv/linux-x86_64/uv.sha256",
    "bootstrap/ensure_uv.sh",
    "bootstrap/startup_wrapper.sh",
]

REQUIRED_RUNTIME = [
    "sk/results/false_rejects/current.json",
]


def exists(uri: str) -> bool:
    return (
        subprocess.run(
            ["gcloud", "storage", "ls", uri],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def has_snapshot_leaf(runtime_root: str, results_prefix: str, leaf_name: str) -> bool:
    uri = f"{runtime_root}/{results_prefix.rstrip('/')}/snapshots/*/{leaf_name}"
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0 and bool((proc.stdout or "").strip())


@click.command()
@bucket_option
@click.option(
    "--require-runner",
    is_flag=True,
    help="Also require canonical runner binary object to exist in runtime namespace.",
)
def main(bucket: str, require_runner: bool) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    code_root = code_bucket_root_uri(bucket)
    runtime_root = runtime_bucket_root_uri(bucket)
    missing = False

    click.echo(f"Validating code root: {code_root}")
    for rel in REQUIRED_CODE:
        uri = f"{code_root}/{rel}"
        if exists(uri):
            click.echo(f"FOUND {uri}")
        else:
            click.echo(f"::error::Missing required code object: {uri}", err=True)
            missing = True

    click.echo(f"Validating runtime root: {runtime_root}")
    for rel in REQUIRED_RUNTIME:
        uri = f"{runtime_root}/{rel}"
        if exists(uri):
            click.echo(f"FOUND {uri}")
        else:
            click.echo(f"::error::Missing required runtime object: {uri}", err=True)
            missing = True

    results_prefix = "sk/results/false_rejects"
    if has_snapshot_leaf(runtime_root, results_prefix, "latest.json"):
        click.echo(f"FOUND snapshot latest.json under {runtime_root}/{results_prefix}/snapshots/")
    else:
        click.echo(
            f"::error::Missing canonical snapshot latest.json under {runtime_root}/{results_prefix}/snapshots/",
            err=True,
        )
        missing = True

    if has_snapshot_leaf(runtime_root, results_prefix, "ci_verdict.json"):
        click.echo(f"FOUND snapshot ci_verdict.json under {runtime_root}/{results_prefix}/snapshots/")
    else:
        click.echo(
            f"::error::Missing canonical snapshot ci_verdict.json under {runtime_root}/{results_prefix}/snapshots/",
            err=True,
        )
        missing = True

    if require_runner:
        runner_uri = f"{runtime_root}/sk/runners/sk_gcc_release/kardome_runner"
        if exists(runner_uri):
            click.echo(f"FOUND {runner_uri}")
        else:
            click.echo(f"::error::Missing required object: {runner_uri}", err=True)
            missing = True

    if missing:
        return 1

    click.echo("Bucket contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

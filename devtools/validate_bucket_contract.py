#!/usr/bin/env python3
"""Validate required objects and ensure legacy _sandbox is absent."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from shared_bucket_env import bucket_option, bucket_prefix_option, bucket_root_uri

REQUIRED_STATIC = [
    "root_orchestrator.py",
    "bmt_projects.json",
    "bmt_root_results.json",
    "sk/bmt_manager.py",
    "sk/config/bmt_jobs.json",
    "sk/config/input_template.json",
    "sk/runners/sk_gcc_release/runner_latest_meta.json",
    "sk/results/false_rejects/latest.json",
    "sk/results/false_rejects/last_passing.json",
    "sk/results/sk_bmt_results.json",
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


@click.command()
@bucket_option
@bucket_prefix_option
@click.option(
    "--require-runner",
    is_flag=True,
    help="Also require canonical runner binary object to exist.",
)
def main(bucket: str, bucket_prefix: str, require_runner: bool) -> int:
    if not bucket:
        click.echo("::error::Set BUCKET (or GCS_BUCKET)", err=True)
        return 1

    root = bucket_root_uri(bucket, bucket_prefix)

    missing = False
    for rel in REQUIRED_STATIC:
        uri = f"{root}/{rel}"
        if exists(uri):
            click.echo(f"FOUND {uri}")
        else:
            click.echo(f"::error::Missing required object: {uri}", err=True)
            missing = True

    if require_runner:
        runner_uri = f"{root}/sk/runners/sk_gcc_release/kardome_runner"
        if exists(runner_uri):
            click.echo(f"FOUND {runner_uri}")
        else:
            click.echo(f"::error::Missing required object: {runner_uri}", err=True)
            missing = True

    sandbox_uri = f"{root}/_sandbox"
    if exists(sandbox_uri):
        click.echo(f"::error::Legacy _sandbox prefix exists under {sandbox_uri}", err=True)
        missing = True
    else:
        click.echo(f"OK no _sandbox prefix under {root}")

    if missing:
        return 1

    click.echo("Bucket contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

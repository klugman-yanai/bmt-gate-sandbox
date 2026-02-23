#!/usr/bin/env python3
"""Sync local remote/ mirror into bucket."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from shared_bucket_env import bucket_option, bucket_prefix_option, bucket_root_uri

DEFAULT_RUNTIME_EXCLUDES = (
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/inputs(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)sk/results(/|$)",
)


@click.command()
@bucket_option
@bucket_prefix_option
@click.option("--src-dir", default="remote", help="Source directory to sync")
@click.option("--delete", is_flag=True, help="Delete unmatched destination objects")
@click.option(
    "--include-runtime-artifacts",
    is_flag=True,
    help="Include runtime-generated paths (triggers, inputs, outputs, results).",
)
def main(bucket: str, bucket_prefix: str, src_dir: str, delete: bool, include_runtime_artifacts: bool) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    src = Path(src_dir)
    if not src.is_dir():
        click.echo(f"::error::Missing source directory: {src}", err=True)
        return 1

    dest = bucket_root_uri(bucket, bucket_prefix)

    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    if not include_runtime_artifacts:
        for pattern in DEFAULT_RUNTIME_EXCLUDES:
            cmd.extend(["--exclude", pattern])
    cmd.extend([str(src), dest])

    click.echo(f"Syncing {src}/ -> {dest}/")
    if not include_runtime_artifacts:
        click.echo("Excluding runtime-generated paths by default (use --include-runtime-artifacts to override).")
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

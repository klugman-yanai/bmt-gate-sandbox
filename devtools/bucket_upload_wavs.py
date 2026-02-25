#!/usr/bin/env python3
"""Upload wav dataset tree to canonical inputs prefix."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from shared_bucket_env import bucket_option, bucket_prefix_option, normalize_prefix, runtime_bucket_root_uri


@click.command()
@bucket_option
@bucket_prefix_option
@click.option(
    "--source-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="Local wav directory (explicit; e.g. data/sk/inputs/false_rejects)",
)
@click.option("--dest-prefix", default="sk/inputs/false_rejects", help="Destination prefix in bucket")
def main(bucket: str, bucket_prefix: str, source_dir: Path, dest_prefix: str) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    source = source_dir.resolve()

    parent = normalize_prefix(bucket_prefix)
    root = runtime_bucket_root_uri(bucket, parent)
    dest = f"{root}/{dest_prefix.lstrip('/')}"

    click.echo(f"Syncing wavs {source}/ -> {dest}/")
    return subprocess.run(["gcloud", "storage", "rsync", "--recursive", str(source), dest], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

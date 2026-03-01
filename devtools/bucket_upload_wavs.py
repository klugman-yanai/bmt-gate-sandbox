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
from shared_bucket_env import bucket_option, runtime_bucket_root_uri


@click.command()
@bucket_option
@click.option(
    "--source-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="Local wav directory (explicit; e.g. data/sk/inputs/false_rejects)",
)
@click.option("--dest-prefix", default="sk/inputs/false_rejects", help="Destination prefix in bucket")
@click.option(
    "--force",
    is_flag=True,
    help="Force upload even if destination already matches (default: skip when already in sync).",
)
def main(
    bucket: str,
    source_dir: Path,
    dest_prefix: str,
    force: bool,
) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    source = source_dir.resolve()

    root = runtime_bucket_root_uri(bucket)
    dest = f"{root}/{dest_prefix.lstrip('/')}"

    if not force:
        local_files = list(source.rglob("*"))
        local_files = [p for p in local_files if p.is_file()]
        local_count = len(local_files)
        local_bytes = sum(p.stat().st_size for p in local_files)

        ls_proc = subprocess.run(
            ["gcloud", "storage", "ls", "-r", dest],
            capture_output=True,
            text=True,
            check=False,
        )
        if ls_proc.returncode == 0 and local_count > 0:
            remote_count = len([line for line in ls_proc.stdout.splitlines() if line.strip()])
            du_proc = subprocess.run(
                ["gcloud", "storage", "du", "-s", "-c", dest],
                capture_output=True,
                text=True,
                check=False,
            )
            remote_bytes = None
            if du_proc.returncode == 0 and du_proc.stdout.strip():
                parts = du_proc.stdout.strip().split()
                if parts and parts[0].isdigit():
                    remote_bytes = int(parts[0])
            if remote_bytes is not None and remote_count == local_count and remote_bytes == local_bytes:
                click.echo(
                    f"Dataset already in sync at {dest} (count={local_count}, size={local_bytes} bytes); "
                    "skipping. Use --force to re-upload."
                )
                return 0

    click.echo(f"Syncing wavs {source}/ -> {dest}/")
    return subprocess.run(["gcloud", "storage", "rsync", "--recursive", str(source), dest], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

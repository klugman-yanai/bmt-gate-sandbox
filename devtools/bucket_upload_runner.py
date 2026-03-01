#!/usr/bin/env python3
"""Upload runner with single previous-version rotation + metadata.

Default runner-path and runner-uri are for the current sk project; override via
CLI for other projects.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from shared_bucket_env import bucket_option, runtime_bucket_root_uri


def run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=capture)


@click.command()
@bucket_option
@click.option(
    "--runner-path",
    default="repo/staging/runners/sk_gcc_release/kardome_runner",
    help="Local path to runner binary",
)
@click.option(
    "--runner-uri",
    default="sk/runners/sk_gcc_release/kardome_runner",
    help="Destination URI path in bucket",
)
@click.option("--source", default="sandbox_manual", help="Source label for metadata")
@click.option(
    "--source-ref",
    default=os.environ.get("SOURCE_REF", ""),
    help="Source ref (defaults to git HEAD)",
)
@click.option("--force", is_flag=True, help="Force upload even if size matches")
def main(
    bucket: str,
    runner_path: str,
    runner_uri: str,
    source: str,
    source_ref: str,
    force: bool,
) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    runner = Path(runner_path)
    if not runner.is_file():
        click.echo(f"::error::Runner file not found: {runner}", err=True)
        return 1

    if not source_ref:
        proc = run(["git", "rev-parse", "--short", "HEAD"], capture=True)
        source_ref = proc.stdout.strip() if proc.returncode == 0 else "unknown"

    bucket_root = runtime_bucket_root_uri(bucket)
    runner_uri_clean = runner_uri.lstrip("/")
    canonical_uri = f"{bucket_root}/{runner_uri_clean}"
    previous_uri = f"{canonical_uri}.previous"
    meta_uri = f"{bucket_root}/{Path(runner_uri_clean).parent.as_posix()}/runner_latest_meta.json"

    local_size = runner.stat().st_size

    remote_exists = run(["gcloud", "storage", "ls", canonical_uri]).returncode == 0
    remote_size = None
    if remote_exists:
        details = run(["gcloud", "storage", "ls", "-L", canonical_uri], capture=True)
        if details.returncode == 0:
            for line in details.stdout.splitlines():
                if "Content-Length:" in line:
                    value = line.split(":", 1)[1].strip().replace(",", "")
                    if value.isdigit():
                        remote_size = int(value)
                    break

    if (not force) and remote_exists and remote_size is not None and remote_size == local_size:
        click.echo(f"Runner appears unchanged (size={local_size}); skipping upload. Use --force to override.")
        return 0

    if remote_exists:
        cp_prev = run(["gcloud", "storage", "cp", canonical_uri, previous_uri, "--quiet"])
        if cp_prev.returncode != 0:
            return cp_prev.returncode
        click.echo(f"Rotated previous runner to {previous_uri}")

    cp_new = run(["gcloud", "storage", "cp", str(runner), canonical_uri, "--quiet"])
    if cp_new.returncode != 0:
        return cp_new.returncode

    meta = {
        "uploaded_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "source_ref": source_ref,
        "size_bytes": local_size,
        "bucket_path": canonical_uri,
    }

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
        json.dump(meta, tmp, indent=2)
        _ = tmp.write("\n")
        tmp_path = Path(tmp.name)

    try:
        cp_meta = run(["gcloud", "storage", "cp", str(tmp_path), meta_uri, "--quiet"])
        if cp_meta.returncode != 0:
            return cp_meta.returncode
    finally:
        tmp_path.unlink(missing_ok=True)

    click.echo(f"Uploaded runner to {canonical_uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

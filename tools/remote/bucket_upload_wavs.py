#!/usr/bin/env python3
"""Upload wav dataset tree to canonical inputs prefix."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tools.shared.bucket_env import bucket_from_env, runtime_bucket_root_uri, truthy


class BucketUploadWavs:
    """Upload wav dataset tree to canonical inputs prefix."""

    def run(
        self,
        *,
        bucket: str,
        source_dir: str | Path,
        dest_prefix: str = "sk/inputs/false_rejects",
        force: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        source = Path(source_dir).resolve()
        if not source.is_dir():
            print(f"::error::Missing source directory: {source}", file=sys.stderr)
            return 1

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
                    print(
                        f"Dataset already in sync at {dest} (count={local_count}, size={local_bytes} bytes); "
                        "skipping. Use BMT_FORCE=1 to re-upload."
                    )
                    return 0

        print(f"Syncing wavs {source}/ -> {dest}/")
        return subprocess.run(
            ["gcloud", "storage", "rsync", "--recursive", str(source), dest],
            check=False,
        ).returncode


if __name__ == "__main__":
    bucket = bucket_from_env()
    source_dir = (os.environ.get("BMT_SOURCE_DIR") or "").strip()
    if not source_dir:
        print("::error::Set BMT_SOURCE_DIR (e.g. data/sk/inputs/false_rejects)", file=sys.stderr)
        raise SystemExit(1)
    dest_prefix = (os.environ.get("BMT_DEST_PREFIX") or "").strip() or "sk/inputs/false_rejects"
    force = truthy(os.environ.get("BMT_FORCE"))
    raise SystemExit(
        BucketUploadWavs().run(
            bucket=bucket,
            source_dir=source_dir,
            dest_prefix=dest_prefix,
            force=force,
        )
    )

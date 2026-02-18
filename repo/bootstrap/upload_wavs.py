#!/usr/bin/env python3
"""Upload wav dataset tree to canonical inputs prefix."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--bucket", default=os.environ.get("BUCKET") or os.environ.get("GCS_BUCKET", "")
    )
    _ = parser.add_argument(
        "--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", "")
    )
    _ = parser.add_argument("--source-dir", default="repo/staging/wavs/false_rejects")
    _ = parser.add_argument("--dest-prefix", default="sk/inputs/false_rejects")
    args = parser.parse_args()

    if not args.bucket:
        print("::error::Set BUCKET (or GCS_BUCKET)", file=sys.stderr)
        return 1

    source = Path(args.source_dir)
    if not source.is_dir():
        print(f"::error::Source wav directory not found: {source}", file=sys.stderr)
        return 1

    prefix = args.bucket_prefix.strip("/")
    dest_prefix = args.dest_prefix.lstrip("/")
    root = f"gs://{args.bucket}/{prefix}" if prefix else f"gs://{args.bucket}"
    dest = f"{root}/{dest_prefix}"

    print(f"Syncing wavs {source}/ -> {dest}/")
    return subprocess.run(
        ["gcloud", "storage", "rsync", "--recursive", str(source), dest], check=False
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())

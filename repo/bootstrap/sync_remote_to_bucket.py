#!/usr/bin/env python3
"""Sync local remote/ mirror into bucket."""

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
    _ = parser.add_argument("--src-dir", default="remote")
    _ = parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    if not args.bucket:
        print("::error::Set BUCKET (or GCS_BUCKET)", file=sys.stderr)
        return 1

    src = Path(args.src_dir)
    if not src.is_dir():
        print(f"::error::Missing source directory: {src}", file=sys.stderr)
        return 1

    prefix = args.bucket_prefix.strip("/")
    dest = f"gs://{args.bucket}/{prefix}" if prefix else f"gs://{args.bucket}"

    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if args.delete:
        cmd.append("--delete-unmatched-destination-objects")
    cmd.extend([str(src), dest])

    print(f"Syncing {src}/ -> {dest}/")
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

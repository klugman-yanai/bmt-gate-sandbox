#!/usr/bin/env python3
"""Upload wav dataset tree to canonical inputs prefix."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from bucket_env import bucket_root_uri, get_bucket_from_env


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--bucket", default=get_bucket_from_env())
    _ = parser.add_argument("--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", ""))
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

    root = bucket_root_uri(args.bucket, args.bucket_prefix)
    dest = f"{root}/{args.dest_prefix.lstrip('/')}"

    print(f"Syncing wavs {source}/ -> {dest}/")
    return subprocess.run(["gcloud", "storage", "rsync", "--recursive", str(source), dest], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

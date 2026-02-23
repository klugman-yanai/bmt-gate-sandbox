#!/usr/bin/env python3
"""Sync local remote/ mirror into bucket."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Allow importing bucket_env when run as devtools/sync_remote_to_bucket.py from repo root.
_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from bucket_env import bucket_root_uri, get_bucket_from_env


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--bucket", default=get_bucket_from_env())
    _ = parser.add_argument("--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", ""))
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

    dest = bucket_root_uri(args.bucket, args.bucket_prefix)

    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if args.delete:
        cmd.append("--delete-unmatched-destination-objects")
    cmd.extend([str(src), dest])

    print(f"Syncing {src}/ -> {dest}/")
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

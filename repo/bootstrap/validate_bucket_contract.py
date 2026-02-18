#!/usr/bin/env python3
"""Validate required objects and ensure legacy _sandbox is absent."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

REQUIRED_STATIC = [
    "root_orchestrator.py",
    "bmt_projects.json",
    "bmt_root_results.json",
    "sk/sk_bmt_manager.py",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--bucket", default=os.environ.get("BUCKET") or os.environ.get("GCS_BUCKET", "")
    )
    _ = parser.add_argument(
        "--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", "")
    )
    _ = parser.add_argument(
        "--require-runner",
        action="store_true",
        help="Also require canonical runner binary object to exist.",
    )
    args = parser.parse_args()

    if not args.bucket:
        print("::error::Set BUCKET (or GCS_BUCKET)", file=sys.stderr)
        return 1

    prefix = args.bucket_prefix.strip("/")
    root = f"gs://{args.bucket}/{prefix}" if prefix else f"gs://{args.bucket}"

    missing = False
    for rel in REQUIRED_STATIC:
        uri = f"{root}/{rel}"
        if exists(uri):
            print(f"FOUND {uri}")
        else:
            print(f"::error::Missing required object: {uri}")
            missing = True

    if args.require_runner:
        runner_uri = f"{root}/sk/runners/sk_gcc_release/kardome_runner"
        if exists(runner_uri):
            print(f"FOUND {runner_uri}")
        else:
            print(f"::error::Missing required object: {runner_uri}")
            missing = True

    sandbox_uri = f"{root}/_sandbox"
    if exists(sandbox_uri):
        print(f"::error::Legacy _sandbox prefix exists under {sandbox_uri}")
        missing = True
    else:
        print(f"OK no _sandbox prefix under {root}")

    if missing:
        return 1

    print("Bucket contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

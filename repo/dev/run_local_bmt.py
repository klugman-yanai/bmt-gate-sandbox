#!/usr/bin/env python3
"""Local convenience wrapper to run one project+BMT via root orchestrator."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--bucket", default=os.environ.get("BUCKET") or os.environ.get("GCS_BUCKET", "")
    )
    _ = parser.add_argument(
        "--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", "")
    )
    _ = parser.add_argument("--project", default=os.environ.get("PROJECT", "sk"))
    _ = parser.add_argument(
        "--bmt-id", default=os.environ.get("BMT_ID", "false_reject_namuh")
    )
    _ = parser.add_argument(
        "--run-context",
        default=os.environ.get("RUN_CONTEXT", "manual"),
        choices=["dev", "pr", "manual"],
    )
    _ = parser.add_argument(
        "--workspace-root",
        default=os.environ.get("WORKSPACE_ROOT", os.path.expanduser("~/sk_runtime")),
    )
    args = parser.parse_args()

    if not args.bucket:
        print("::error::Set BUCKET (or GCS_BUCKET)", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        "remote/root_orchestrator.py",
        "--bucket",
        args.bucket,
        "--bucket-prefix",
        args.bucket_prefix,
        "--project",
        args.project,
        "--bmt-id",
        args.bmt_id,
        "--run-context",
        args.run_context,
        "--workspace-root",
        args.workspace_root,
        "--human",
    ]
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

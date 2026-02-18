#!/usr/bin/env python3
"""Thin CI trigger for one project+BMT run on VM."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from typing import cast


def run_ok(cmd: list[str]) -> bool:
    return subprocess.run(
        cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("vm_name")
    _ = parser.add_argument("gcp_zone")
    _ = parser.add_argument("bucket")
    _ = parser.add_argument("project")
    _ = parser.add_argument("bmt_id")
    _ = parser.add_argument("run_context", nargs="?", default="manual")
    _ = parser.add_argument(
        "bucket_prefix", nargs="?", default=os.environ.get("BMT_BUCKET_PREFIX", "")
    )
    args = parser.parse_args()
    vm_name = cast(str, args.vm_name)
    gcp_zone = cast(str, args.gcp_zone)
    bucket = cast(str, args.bucket)
    project = cast(str, args.project)
    bmt_id = cast(str, args.bmt_id)
    run_context = cast(str, args.run_context)
    bucket_prefix = cast(str, args.bucket_prefix)

    prefix = bucket_prefix.strip("/")
    bucket_root = f"gs://{bucket}/{prefix}" if prefix else f"gs://{bucket}"
    root_orchestrator_uri = f"{bucket_root}/root_orchestrator.py"

    if not run_ok(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            "--zone",
            gcp_zone,
            "--format=value(name)",
        ]
    ):
        print(f"::error::VM {vm_name} not found in zone {gcp_zone}.", file=sys.stderr)
        return 1

    if not run_ok(["gcloud", "storage", "ls", root_orchestrator_uri]):
        print(f"::error::Missing root orchestrator at {root_orchestrator_uri}", file=sys.stderr)
        return 1

    cmd_parts = [
        "set -euo pipefail",
        "mkdir -p ~/sk_runtime/bin",
        (
            f"gcloud storage cp {shlex.quote(root_orchestrator_uri)}"
            " ~/sk_runtime/bin/root_orchestrator.py --quiet"
        ),
        "chmod +x ~/sk_runtime/bin/root_orchestrator.py",
        (
            "python3 ~/sk_runtime/bin/root_orchestrator.py "
            f"--bucket {shlex.quote(bucket)} "
            f"--bucket-prefix {shlex.quote(prefix)} "
            f"--project {shlex.quote(project)} "
            f"--bmt-id {shlex.quote(bmt_id)} "
            f"--run-context {shlex.quote(run_context)} "
            "--workspace-root ~/sk_runtime"
        ),
    ]
    remote_cmd = "; ".join(cmd_parts)

    print(f"Triggering {project}.{bmt_id} on {vm_name} ({run_context})")
    proc = subprocess.run(
        [
            "gcloud",
            "compute",
            "ssh",
            vm_name,
            "--zone",
            gcp_zone,
            "--quiet",
            "--tunnel-through-iap",
            f"--command={remote_cmd}",
        ],
        check=False,
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

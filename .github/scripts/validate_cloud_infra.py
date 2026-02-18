#!/usr/bin/env python3
"""Validate core cloud resources before remote orchestration."""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import cast


def run_check(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("bucket")
    _ = parser.add_argument("vm_name")
    _ = parser.add_argument("zone")
    args = parser.parse_args()
    bucket = cast(str, args.bucket)
    vm_name = cast(str, args.vm_name)
    zone = cast(str, args.zone)

    bucket_uri = f"gs://{bucket}"
    print(f"Validating bucket {bucket_uri}...")
    rc, _ = run_check(["gcloud", "storage", "ls", bucket_uri])
    if rc != 0:
        print(
            f"::warning::Bucket {bucket_uri} could not be listed from CI identity. Continuing; VM-side orchestration may still succeed."
        )

    print(f"Validating VM {vm_name} in zone {zone}...")
    rc, _ = run_check(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            "--zone",
            zone,
            "--format=value(name)",
        ]
    )
    if rc != 0:
        print(
            f"::error::VM {vm_name} not found in zone {zone}. Create it or update repo variable BMT_VM_NAME/GCP_ZONE.",
            file=sys.stderr,
        )
        return 1

    rc, status = run_check(
        [
            "gcloud",
            "compute",
            "instances",
            "describe",
            vm_name,
            "--zone",
            zone,
            "--format=value(status)",
        ]
    )
    if rc == 0 and status and status != "RUNNING":
        print(f"::warning::VM {vm_name} exists but status is {status}. SSH/orchestration may fail until it is running.")

    print("Cloud infra validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Set VM metadata so startup-script-url points at the GCS-hosted entrypoint.

Required env: GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, GCS_BUCKET.
Optional: BMT_REPO_ROOT (default /opt/bmt).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from gcp.image.path_utils import DEFAULT_BMT_REPO_ROOT, SCRIPTS_STARTUP_ENTRYPOINT


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = os.environ.get("GCP_ZONE", "").strip()
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    repo_root = os.environ.get("BMT_REPO_ROOT", "").strip() or DEFAULT_BMT_REPO_ROOT

    if not all([project, zone, vm_name, bucket]):
        print("::error::Set GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, and GCS_BUCKET.", file=sys.stderr)
        print("Optional: BMT_REPO_ROOT. Example: GCP_PROJECT=p GCP_ZONE=z BMT_LIVE_VM=v GCS_BUCKET=b", file=sys.stderr)
        return 1

    # Bucket root only (no code/ in GCS); URL is gs://bucket/scripts/startup_entrypoint.sh
    entrypoint_url = f"gs://{bucket}/{SCRIPTS_STARTUP_ENTRYPOINT}"
    print(f"Checking entrypoint at {entrypoint_url}...")
    r = subprocess.run(
        ["gcloud", "storage", "ls", entrypoint_url],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        print("::error::Could not find startup entrypoint at:", entrypoint_url, file=sys.stderr)
        print("Sync code first: just sync-gcp && just verify-sync", file=sys.stderr)
        return 1

    print(f"Setting VM metadata and startup-script-url for {vm_name} (bucket={bucket})...")
    metadata = f"GCS_BUCKET={bucket},BMT_REPO_ROOT={repo_root},startup-script=,startup-script-url={entrypoint_url}"
    r = subprocess.run(
        [
            "gcloud", "compute", "instances", "add-metadata", vm_name,
            "--zone", zone,
            "--project", project,
            "--metadata", metadata,
        ],
        check=False,
    )
    if r.returncode != 0:
        return 1
    print(f"Done. On next boot the VM will run startup from {entrypoint_url}.")
    print("Rollback: python -m gcp.image.scripts.rollback_startup_to_inline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Set VM metadata so startup-script-url points at the GCS-hosted entrypoint.

Required env: GCP_PROJECT, BMT_LIVE_VM, GCS_BUCKET.
Zone and repo root use fixed defaults (not overridable via env).
"""

from __future__ import annotations

import os
import subprocess

from gcp.image.config.constants import DEFAULT_GCP_ZONE
from gcp.image.path_utils import DEFAULT_BMT_REPO_ROOT, SCRIPTS_STARTUP_ENTRYPOINT


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = DEFAULT_GCP_ZONE
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    repo_root = DEFAULT_BMT_REPO_ROOT

    if not all([project, vm_name, bucket]):
        return 1

    # Bucket root only (no code/ in GCS); URL is gs://bucket/scripts/startup_entrypoint.sh
    entrypoint_url = f"gs://{bucket}/{SCRIPTS_STARTUP_ENTRYPOINT}"
    r = subprocess.run(
        ["gcloud", "storage", "ls", entrypoint_url],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return 1

    metadata = f"GCS_BUCKET={bucket},BMT_REPO_ROOT={repo_root},startup-script=,startup-script-url={entrypoint_url}"
    r = subprocess.run(
        [
            "gcloud",
            "compute",
            "instances",
            "add-metadata",
            vm_name,
            "--zone",
            zone,
            "--project",
            project,
            "--metadata",
            metadata,
        ],
        check=False,
    )
    if r.returncode != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

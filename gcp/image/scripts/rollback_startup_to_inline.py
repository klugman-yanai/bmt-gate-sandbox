#!/usr/bin/env python3
"""Roll back startup mode to inline startup-script metadata (legacy mode).

Required env: GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, GCS_BUCKET.
Optional: BMT_REPO_ROOT (default /opt/bmt).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from gcp.image.path_utils import DEFAULT_BMT_REPO_ROOT


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = os.environ.get("GCP_ZONE", "").strip()
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    repo_root = os.environ.get("BMT_REPO_ROOT", "").strip() or DEFAULT_BMT_REPO_ROOT

    if not all([project, zone, vm_name, bucket]):
        print("::error::Set GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, and GCS_BUCKET.", file=sys.stderr)
        return 1

    entrypoint = Path(__file__).resolve().parent / "startup_entrypoint.sh"
    if not entrypoint.is_file():
        print(f"::error::Missing startup_entrypoint.sh at {entrypoint}", file=sys.stderr)
        return 1

    print(f"Rolling back {vm_name} to inline startup-script (entrypoint={entrypoint})...")
    r = subprocess.run(
        [
            "gcloud", "compute", "instances", "add-metadata", vm_name,
            "--zone", zone,
            "--project", project,
            "--metadata", f"GCS_BUCKET={bucket},BMT_REPO_ROOT={repo_root},startup-script-url=",
            "--metadata-from-file", f"startup-script={entrypoint}",
        ],
        check=False,
    )
    if r.returncode != 0:
        return 1
    print("Done. VM will use inline startup-script on next boot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

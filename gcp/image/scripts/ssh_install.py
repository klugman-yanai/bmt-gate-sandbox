#!/usr/bin/env python3
"""SSH into the BMT VM and run dependency install (pip) so deps are persistent on the VM's disk.

Required env: GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM.
Optional: BMT_REPO_ROOT (default /opt/bmt).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from whenever import Instant

from gcp.image.path_utils import DEFAULT_BMT_REPO_ROOT


def _log(msg: str) -> None:
    ts = Instant.now().format_iso(unit="second")
    print(f"[{ts}] [ssh_install] {msg}")


def _log_err(msg: str) -> None:
    ts = Instant.now().format_iso(unit="second")
    print(f"[{ts}] [ssh_install] {msg}", file=sys.stderr)


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = os.environ.get("GCP_ZONE", "").strip()
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    repo_root = os.environ.get("BMT_REPO_ROOT", "").strip() or DEFAULT_BMT_REPO_ROOT

    if not all([project, zone, vm_name]):
        _log_err("::error::Set GCP_PROJECT, GCP_ZONE, and BMT_LIVE_VM.")
        _log_err("Example: GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_LIVE_VM=bmt-vm")
        return 1

    _log(f"Running install_deps on {vm_name} ({repo_root})...")
    cmd = f"set -euo pipefail; cd '{repo_root}'; python3 scripts/install_deps.py '{repo_root}'"
    r = subprocess.run(
        ["gcloud", "compute", "ssh", vm_name, "--zone", zone, "--project", project, "--", "bash", "-c", cmd],
        check=False,
    )
    if r.returncode != 0:
        return 1
    _log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

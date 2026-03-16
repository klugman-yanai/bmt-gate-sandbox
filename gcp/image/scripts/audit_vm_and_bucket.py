#!/usr/bin/env python3
"""Audit VM filesystem and GCS bucket layout; report bloat.

Required env: GCP_PROJECT, BMT_LIVE_VM, GCS_BUCKET.
Zone and repo root use fixed defaults (not overridable via env).
"""

from __future__ import annotations

import os
import subprocess

from whenever import Instant

from gcp.image.config.constants import DEFAULT_GCP_ZONE
from gcp.image.path_utils import DEFAULT_BMT_REPO_ROOT


def _log(_msg: str) -> None:
    Instant.now().format_iso(unit="second")


def main() -> int:
    project = os.environ.get("GCP_PROJECT", "").strip()
    zone = (os.environ.get("GCP_ZONE") or "").strip() or DEFAULT_GCP_ZONE
    vm_name = os.environ.get("BMT_LIVE_VM", "").strip()
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    repo_root = os.environ.get("BMT_REPO_ROOT", "").strip() or DEFAULT_BMT_REPO_ROOT

    if not all([project, vm_name, bucket]):
        return 1

    _log("=== VM filesystem audit (gcloud compute ssh) ===")
    cmd = (
        f"set -e; echo '--- Disk usage ---'; df -h / /opt 2>/dev/null || df -h; "
        f"echo '--- Repo root {repo_root} ---'; "
        f"if [ -d '{repo_root}' ]; then ls -la '{repo_root}'; "
        f"du -sh '{repo_root}'/.venv '{repo_root}' 2>/dev/null || true; else echo 'Missing'; fi; "
        "echo '--- Workspace (bmt_workspace + legacy sk_runtime) ---'; "
        "du -sh $HOME/bmt_workspace 2>/dev/null || echo 'bmt_workspace: N/A'; "
        "du -sh $HOME/sk_runtime 2>/dev/null || echo 'sk_runtime: N/A'; "
        "echo '--- Temp / large ---'; du -sh /tmp 2>/dev/null || true; "
        f"echo '--- Bloat check: old trigger/cache under repo ---'; "
        f"find '{repo_root}' -maxdepth 4 -type f -name '*.json' -mtime +7 2>/dev/null | head -20 || true"
    )
    subprocess.run(
        ["gcloud", "compute", "ssh", vm_name, "--zone", zone, "--project", project, "--", "bash", "-c", cmd],
        check=False,
    )

    bucket_root = f"gs://{bucket}"
    _log("=== Bucket layout (bucket root only; no code/ or runtime/ prefix) ===")
    subprocess.run(["gcloud", "storage", "ls", f"gs://{bucket}/"], check=False)
    r = subprocess.run(["gcloud", "storage", "ls", f"{bucket_root}/triggers/runs/"], capture_output=True, check=False)
    if r.returncode != 0:
        pass
    r = subprocess.run(["gcloud", "storage", "ls", f"{bucket_root}/sk/results/"], capture_output=True, check=False)
    if r.returncode != 0:
        pass

    _log("=== Bloat: consider removing old run triggers ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

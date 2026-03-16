#!/usr/bin/env python3
"""VM-side bucket contract validation.

Validates bucket root only (no code/ in GCS). Required: GCS_BUCKET. Optional: BMT_RESULTS_PREFIX.
Exit 1 if any check fails. Used by startup_entrypoint.sh before running the watcher.
"""

from __future__ import annotations

import os
import subprocess

from whenever import Instant


def _log(_msg: str) -> None:
    Instant.now().format_iso(unit="second")


def _log_err(_msg: str) -> None:
    Instant.now().format_iso(unit="second")


def _gcloud_ls_exists(uri: str) -> bool:
    r = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode == 0


def _gcloud_ls_recursive(uri: str) -> str:
    r = subprocess.run(
        ["gcloud", "storage", "ls", uri, "--recursive"],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout or ""


def main() -> int:
    bucket = os.environ.get("GCS_BUCKET", "").strip()
    if not bucket:
        _log_err("::error::GCS_BUCKET not set")
        return 1

    bucket_root = f"gs://{bucket}"
    missing = 0

    results_prefix = os.environ.get("BMT_RESULTS_PREFIX", "").strip()
    if results_prefix:
        prefix = results_prefix.rstrip("/")
        _log(f"Validating bucket root: {bucket_root} (results_prefix={prefix})")
        current_uri = f"{bucket_root}/{prefix}/current.json"
        if _gcloud_ls_exists(current_uri):
            _log(f"FOUND {current_uri}")
        else:
            _log_err(f"::error::Missing required object: {current_uri}")
            missing = 1
        snap_uri = f"{bucket_root}/{prefix}/snapshots/"
        listing = _gcloud_ls_recursive(snap_uri)
        if "/latest.json" not in listing:
            _log_err(f"::error::Missing canonical snapshot latest.json under {snap_uri}")
            missing = 1
        if "/ci_verdict.json" not in listing:
            _log_err(f"::error::Missing canonical snapshot ci_verdict.json under {snap_uri}")
            missing = 1
    else:
        _log("BMT_RESULTS_PREFIX not set; skipping snapshot checks")

    if missing:
        _log_err("Bucket contract validation failed")
        return 1
    _log("Bucket contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

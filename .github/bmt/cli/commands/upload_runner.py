"""Upload a project runner (kardome_runner + libKardome.so) to GCS."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from cli import gcloud
from cli.shared import require_env, runtime_bucket_root_uri


def run() -> None:
    """Upload runner binary and project lib to GCS.
    Reads RUNNER_DIR, LIB_DIR, PROJECT, PRESET, SOURCE_REF, GCS_BUCKET."""
    bucket = require_env("GCS_BUCKET")
    project = require_env("PROJECT")
    preset = require_env("PRESET")
    source_ref = os.environ.get("SOURCE_REF", "")
    runner_dir = Path(os.environ.get("RUNNER_DIR", "artifact/Runners"))
    lib_dir_raw = os.environ.get("LIB_DIR", "artifact/Kardome")
    lib_dir = Path(lib_dir_raw) if lib_dir_raw else None

    if not runner_dir.is_dir():
        raise RuntimeError(f"Runner directory does not exist: {runner_dir}")
    if lib_dir is not None and not lib_dir.is_dir():
        lib_dir = None  # optional — skip if not present

    root = runtime_bucket_root_uri(bucket)
    dest_prefix = f"{project}/runners/{preset}"

    runner_binary = runner_dir / "kardome_runner"
    if not runner_binary.is_file():
        raise RuntimeError(f"kardome_runner not found in {runner_dir}")

    uploaded: list[dict[str, str | int]] = []

    runner_dest = f"{root}/{dest_prefix}/kardome_runner"
    rc, err = gcloud.run_capture_retry(["gcloud", "storage", "cp", str(runner_binary), runner_dest, "--quiet"])
    if rc != 0:
        raise RuntimeError(f"Failed to upload kardome_runner: {err}")
    uploaded.append({"name": "kardome_runner", "size": runner_binary.stat().st_size})
    print(f"Uploaded kardome_runner -> {runner_dest}")

    if lib_dir is not None:
        lib_file = lib_dir / "libKardome.so"
        if lib_file.is_file():
            lib_dest = f"{root}/{dest_prefix}/libKardome.so"
            rc, err = gcloud.run_capture_retry(["gcloud", "storage", "cp", str(lib_file), lib_dest, "--quiet"])
            if rc != 0:
                raise RuntimeError(f"Failed to upload libKardome.so: {err}")
            uploaded.append({"name": "libKardome.so", "size": lib_file.stat().st_size})
            print(f"Uploaded libKardome.so -> {lib_dest}")

    meta = {
        "uploaded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_ref": source_ref,
        "project": project,
        "preset": preset,
        "files": uploaded,
    }
    with tempfile.TemporaryDirectory(prefix="runner_meta_") as tmp_dir:
        meta_path = Path(tmp_dir) / "runner_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        meta_dest = f"{root}/{dest_prefix}/runner_meta.json"
        rc, err = gcloud.run_capture_retry(["gcloud", "storage", "cp", str(meta_path), meta_dest, "--quiet"])
        if rc != 0:
            raise RuntimeError(f"Failed to upload runner_meta.json: {err}")
    print(f"Uploaded runner_meta.json -> {meta_dest}")
    print(f"Runner upload complete: {len(uploaded)} file(s) for {project}/{preset}")

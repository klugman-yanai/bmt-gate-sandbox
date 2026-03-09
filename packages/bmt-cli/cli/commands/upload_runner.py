"""Upload a project runner (kardome_runner + libKardome.so) to GCS."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cli import gcloud
from cli.shared import require_env, runtime_bucket_root_uri


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_remote_runner_meta(meta_uri: str) -> dict[str, Any] | None:
    """Best-effort load of remote runner metadata; returns None when missing/invalid."""
    rc, out = gcloud.run_capture(["gcloud", "storage", "cat", meta_uri])
    if rc != 0:
        return None
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _remote_files_by_name(meta: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not meta:
        return {}
    files = meta.get("files")
    if not isinstance(files, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in files:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        out[name] = row
    return out


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
        lib_dir = None  # optional; skip if not present

    root = runtime_bucket_root_uri(bucket)
    dest_prefix = f"{project}/runners/{preset}"
    meta_dest = f"{root}/{dest_prefix}/runner_meta.json"

    runner_binary = runner_dir / "kardome_runner"
    if not runner_binary.is_file():
        raise RuntimeError(f"kardome_runner not found in {runner_dir}")

    local_files: list[dict[str, str | int]] = [
        {
            "name": "kardome_runner",
            "size": runner_binary.stat().st_size,
            "sha256": _sha256_file(runner_binary),
            "path": str(runner_binary),
            "dest": f"{root}/{dest_prefix}/kardome_runner",
        }
    ]

    if lib_dir is not None:
        lib_file = lib_dir / "libKardome.so"
        if lib_file.is_file():
            local_files.append(
                {
                    "name": "libKardome.so",
                    "size": lib_file.stat().st_size,
                    "sha256": _sha256_file(lib_file),
                    "path": str(lib_file),
                    "dest": f"{root}/{dest_prefix}/libKardome.so",
                }
            )

    remote_meta = _load_remote_runner_meta(meta_dest)
    remote_files = _remote_files_by_name(remote_meta)

    uploaded: list[dict[str, str | int]] = []
    skipped: list[str] = []

    for row in local_files:
        name = str(row["name"])
        local_size = int(row["size"])
        local_sha = str(row["sha256"])
        remote = remote_files.get(name, {})
        remote_size = int(remote.get("size")) if str(remote.get("size", "")).isdigit() else -1
        remote_sha = str(remote.get("sha256", "")).strip().lower()

        if remote_size == local_size and remote_sha == local_sha:
            skipped.append(name)
            continue

        rc, err = gcloud.run_capture_retry(["gcloud", "storage", "cp", str(row["path"]), str(row["dest"]), "--quiet"])
        if rc != 0:
            raise RuntimeError(f"Failed to upload {name}: {err}")
        uploaded.append({"name": name, "size": local_size, "sha256": local_sha})
        print(f"Uploaded {name} -> {row['dest']}")

    if not uploaded:
        unchanged = ", ".join(skipped) if skipped else "none"
        print(f"Runner upload skipped: no content changes for {project}/{preset} ({unchanged})")
        return

    meta = {
        "uploaded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_ref": source_ref,
        "project": project,
        "preset": preset,
        "files": [
            {
                "name": str(row["name"]),
                "size": int(row["size"]),
                "sha256": str(row["sha256"]),
            }
            for row in local_files
        ],
        "uploaded_files": uploaded,
        "skipped_unchanged_files": skipped,
    }
    with tempfile.TemporaryDirectory(prefix="runner_meta_") as tmp_dir:
        meta_path = Path(tmp_dir) / "runner_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        rc, err = gcloud.run_capture_retry(["gcloud", "storage", "cp", str(meta_path), meta_dest, "--quiet"])
        if rc != 0:
            raise RuntimeError(f"Failed to upload runner_meta.json: {err}")
    print(f"Uploaded runner_meta.json -> {meta_dest}")
    print(f"Runner upload complete: {len(uploaded)} changed file(s) for {project}/{preset}")

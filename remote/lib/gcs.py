"""Shared GCS, time, and JSON utilities for VM-side scripts."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class GCSError(RuntimeError):
    """Generic error for GCS/JSON operations."""


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------


def normalize_prefix(prefix: str) -> str:
    return prefix.strip("/")


def bucket_root_uri(bucket: str, prefix: str) -> str:
    p = normalize_prefix(prefix)
    return f"gs://{bucket}/{p}" if p else f"gs://{bucket}"


def bucket_uri(bucket_root: str, path_or_uri: str) -> str:
    if path_or_uri.startswith("gs://"):
        return path_or_uri
    return f"{bucket_root}/{path_or_uri.lstrip('/')}"


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise GCSError(f"Missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# GCS operations (subprocess wrappers)
# ---------------------------------------------------------------------------


def gcloud_cp(src: str, dst: Path | str) -> None:
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(["gcloud", "storage", "cp", src, str(dst_path), "--quiet"], check=True)


def gcloud_upload(src: Path, dst: str) -> None:
    _ = subprocess.run(["gcloud", "storage", "cp", str(src), dst, "--quiet"], check=True)


def gcloud_rsync(src: str, dst: Path | str, delete: bool = False) -> None:
    dst_path = Path(dst) if not isinstance(dst, Path) else dst
    dst_path.mkdir(parents=True, exist_ok=True)
    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    cmd.extend([src, str(dst_path), "--quiet"])
    _ = subprocess.run(cmd, check=True)


def gcloud_rsync_to_gcs(src: Path | str, dst_uri: str, delete: bool = False) -> None:
    src_path = Path(src) if not isinstance(src, Path) else src
    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    cmd.extend([str(src_path), dst_uri, "--quiet"])
    _ = subprocess.run(cmd, check=True)


def gcloud_ls(uri: str, recursive: bool = False) -> list[str]:
    """List objects under a GCS URI prefix. Returns list of full URIs."""
    cmd = ["gcloud", "storage", "ls", uri]
    if recursive:
        cmd.append("--recursive")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def gcloud_ls_json(uri: str, recursive: bool = False) -> list[dict[str, Any]]:
    cmd = ["gcloud", "storage", "ls", "--json"]
    if recursive:
        cmd.append("--recursive")
    cmd.append(uri)
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    out = (proc.stdout or "").strip()
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def gcloud_rm(uri: str, recursive: bool = False) -> bool:
    """Delete a GCS object or prefix (with recursive=True)."""
    cmd = ["gcloud", "storage", "rm", uri, "--quiet"]
    if recursive:
        cmd.append("--recursive")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return proc.returncode == 0


def gcloud_download_json(uri: str) -> dict[str, Any] | None:
    """Download a JSON object from GCS."""
    with tempfile.TemporaryDirectory(prefix="gcs_dl_") as tmp_dir:
        local_path = Path(tmp_dir) / "downloaded.json"
        proc = subprocess.run(
            ["gcloud", "storage", "cp", uri, str(local_path), "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"  Failed to download {uri}: {proc.stderr.strip()}")
            return None
        try:
            return json.loads(local_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  Failed to parse {uri}: {exc}")
            return None


def gcs_exists(uri: str) -> bool:
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def gcs_object_meta(uri: str) -> dict[str, Any] | None:
    entries = gcloud_ls_json(uri)
    if not entries:
        return None
    entry = entries[0]
    return {
        "name": str(entry.get("name") or uri),
        "generation": str(entry.get("generation") or ""),
        "size": int(entry.get("size") or 0),
        "updated": str(entry.get("updated") or ""),
    }

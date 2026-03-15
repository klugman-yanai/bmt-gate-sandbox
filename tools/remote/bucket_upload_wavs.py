#!/usr/bin/env python3
"""Upload wav dataset tree to canonical inputs prefix."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from archivefile import ArchiveFile

from tools.shared.bucket_env import bucket_from_env, bucket_root_uri, truthy

# Suffixes that indicate an archive (archivefile supports zip, tar, 7z, rar and common variants)
_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".7z", ".rar", ".tgz"}
_TAR_GZ_SUFFIX = ".tar.gz"


def _is_archive(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    if name.endswith(_TAR_GZ_SUFFIX):
        return True
    return path.suffix.lower() in _ARCHIVE_SUFFIXES


def _extracted_rsync_root(tmp_dir: Path) -> Path:
    """Return the directory to use as rsync source: single top-level dir if present, else tmp_dir."""
    entries = list(tmp_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return tmp_dir


def _extract_archive(archive_path: Path, dest_dir: Path) -> Path:
    """Extract archive into dest_dir; return path to use as rsync source (see _extracted_rsync_root)."""
    with ArchiveFile(archive_path) as archive:
        archive.extractall(destination=dest_dir)
    return _extracted_rsync_root(dest_dir)


class BucketUploadWavs:
    """Upload wav dataset tree to canonical inputs prefix."""

    def run(
        self,
        *,
        bucket: str,
        source_dir: str | Path,
        dest_prefix: str = "sk/inputs/false_rejects",
        force: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        source = Path(source_dir).resolve()
        if source.is_dir():
            return self._run_rsync(bucket=bucket, source=source, dest_prefix=dest_prefix, force=force)
        if _is_archive(source):
            with tempfile.TemporaryDirectory(prefix="bmt_upload_wavs_") as tmp:
                rsync_source = _extract_archive(source, Path(tmp))
                return self._run_rsync(
                    bucket=bucket,
                    source=rsync_source,
                    dest_prefix=dest_prefix,
                    force=force,
                )
        print(f"::error::Missing source directory: {source}", file=sys.stderr)
        return 1

    def _run_rsync(
        self,
        *,
        bucket: str,
        source: Path,
        dest_prefix: str,
        force: bool,
    ) -> int:
        root = bucket_root_uri(bucket)
        dest = f"{root}/{dest_prefix.lstrip('/')}"

        if not force:
            local_files = list(source.rglob("*"))
            local_files = [p for p in local_files if p.is_file()]
            local_count = len(local_files)
            local_bytes = sum(p.stat().st_size for p in local_files)

            ls_proc = subprocess.run(
                ["gcloud", "storage", "ls", "-r", dest],
                capture_output=True,
                text=True,
                check=False,
            )
            if ls_proc.returncode == 0 and local_count > 0:
                remote_count = len([line for line in ls_proc.stdout.splitlines() if line.strip()])
                du_proc = subprocess.run(
                    ["gcloud", "storage", "du", "-s", "-c", dest],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                remote_bytes = None
                if du_proc.returncode == 0 and du_proc.stdout.strip():
                    parts = du_proc.stdout.strip().split()
                    if parts and parts[0].isdigit():
                        remote_bytes = int(parts[0])
                if remote_bytes is not None and remote_count == local_count and remote_bytes == local_bytes:
                    print(
                        f"Dataset already in sync at {dest} (count={local_count}, size={local_bytes} bytes); "
                        "skipping. Use BMT_FORCE=1 to re-upload."
                    )
                    return 0

        print(f"Syncing wavs {source}/ -> {dest}/")
        proc = subprocess.run(
            ["gcloud", "storage", "rsync", "--recursive", str(source), dest],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 and proc.stderr:
            print(proc.stderr, file=sys.stderr)
        return proc.returncode


if __name__ == "__main__":
    bucket = bucket_from_env()
    source_dir = (os.environ.get("BMT_SOURCE_DIR") or "").strip()
    if not source_dir:
        print("::error::Set BMT_SOURCE_DIR (e.g. data/sk/inputs/false_rejects)", file=sys.stderr)
        raise SystemExit(1)
    dest_prefix = (os.environ.get("BMT_DEST_PREFIX") or "").strip() or "sk/inputs/false_rejects"
    force = truthy(os.environ.get("BMT_FORCE"))
    raise SystemExit(
        BucketUploadWavs().run(
            bucket=bucket,
            source_dir=source_dir,
            dest_prefix=dest_prefix,
            force=force,
        )
    )

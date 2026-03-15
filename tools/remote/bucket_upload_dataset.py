#!/usr/bin/env python3
"""Upload a WAV dataset (zip or folder) to the canonical project inputs path.

GCS destination:  gs://<bucket>/projects/<project>/inputs/<dataset>/
Local mirror:     gcp/remote/projects/<project>/inputs/<dataset>/

Dataset name is auto-detected from the source filename/directory when not
supplied: ``sk_false_rejects.zip`` → ``false_rejects`` (project prefix
stripped if present).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from archivefile import ArchiveFile

from tools.shared.bucket_env import bucket_from_env, bucket_root_uri, truthy

_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".7z", ".rar", ".tgz"}
_TAR_GZ_SUFFIX = ".tar.gz"


def _is_archive(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    if name.endswith(_TAR_GZ_SUFFIX):
        return True
    return path.suffix.lower() in _ARCHIVE_SUFFIXES


def _detect_dataset_name(source: Path, project: str) -> str:
    """Derive dataset name from source path.

    Examples:
        sk_false_rejects.zip  + project=sk  → false_rejects
        false_rejects/                       → false_rejects
        /data/my_dataset.zip                 → my_dataset
    """
    stem = source.stem if source.is_file() else source.name
    # Strip common archive suffixes that don't get removed by .stem (.tar.gz etc.)
    for suffix in (".tar",):
        stem = stem.removesuffix(suffix)
    # Strip <project>_ prefix if present
    prefix = f"{project}_"
    stem = stem.removeprefix(prefix)
    return stem.strip("_- ") or stem


def _rsync_root(extracted: Path) -> Path:
    """Return the actual content root: descend into a single top-level dir."""
    entries = [e for e in extracted.iterdir() if not e.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted


def _extract(archive: Path, dest: Path) -> Path:
    """Extract archive into dest, return rsync-root."""
    with ArchiveFile(archive) as af:
        af.extractall(destination=dest)
    return _rsync_root(dest)


def _gcs_rsync(source: Path, dest_uri: str) -> int:
    print(f"  GCS  {source}/ → {dest_uri}/")
    proc = subprocess.run(
        ["gcloud", "storage", "rsync", "--recursive", str(source), dest_uri],
        check=False,
    )
    return proc.returncode


def _local_sync(source: Path, dest: Path) -> None:
    """Mirror source tree into dest, preserving subdirectory structure."""
    dest.mkdir(parents=True, exist_ok=True)
    for src_file in source.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(source)
        dst_file = dest / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)


class BucketUploadDataset:
    """Upload a WAV dataset (zip or folder) to project inputs paths."""

    def run(
        self,
        *,
        bucket: str,
        project: str,
        source: str | Path,
        dataset_name: str | None = None,
        force: bool = False,
        local_mirror: Path | None = None,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1
        if not project:
            print("::error::project is required", file=sys.stderr)
            return 1

        src = Path(source).resolve()
        if not src.exists():
            print(f"::error::Source not found: {src}", file=sys.stderr)
            return 1

        name = dataset_name or _detect_dataset_name(src, project)
        gcs_dest = f"{bucket_root_uri(bucket)}/projects/{project}/inputs/{name}"

        print(f"Dataset:   {name}")
        print(f"Source:    {src}")
        print(f"GCS dest:  {gcs_dest}/")
        if local_mirror:
            local_dest = local_mirror / "projects" / project / "inputs" / name
            print(f"Local:     {local_dest}/")

        if src.is_dir():
            return self._upload(
                source=src,
                gcs_dest=gcs_dest,
                local_mirror=local_mirror,
                project=project,
                dataset_name=name,
                force=force,
            )
        if _is_archive(src):
            with tempfile.TemporaryDirectory(prefix="bmt_upload_dataset_") as tmp:
                content_root = _extract(src, Path(tmp))
                return self._upload(
                    source=content_root,
                    gcs_dest=gcs_dest,
                    local_mirror=local_mirror,
                    project=project,
                    dataset_name=name,
                    force=force,
                )
        print(f"::error::Source is neither a directory nor a recognised archive: {src}", file=sys.stderr)
        return 1

    def _upload(
        self,
        *,
        source: Path,
        gcs_dest: str,
        local_mirror: Path | None,
        project: str,
        dataset_name: str,
        force: bool,
    ) -> int:
        if not force:
            skip = self._already_synced(source, gcs_dest)
            if skip:
                print(f"Already in sync at {gcs_dest}; skipping. Pass --force to re-upload.")
                if local_mirror:
                    self._sync_local(source, local_mirror, project, dataset_name)
                return 0

        rc = _gcs_rsync(source, gcs_dest)
        if rc != 0:
            return rc

        if local_mirror:
            self._sync_local(source, local_mirror, project, dataset_name)

        n_files = sum(1 for _ in source.rglob("*") if _.is_file())
        print(f"Done: {n_files} file(s) uploaded to {gcs_dest}/")
        return 0

    def _already_synced(self, source: Path, dest_uri: str) -> bool:
        local_files = [p for p in source.rglob("*") if p.is_file()]
        if not local_files:
            return False
        local_count = len(local_files)
        local_bytes = sum(p.stat().st_size for p in local_files)
        ls = subprocess.run(
            ["gcloud", "storage", "ls", "-r", dest_uri],
            capture_output=True,
            text=True,
            check=False,
        )
        if ls.returncode != 0:
            return False
        remote_count = len([ln for ln in ls.stdout.splitlines() if ln.strip() and not ln.endswith(":")])
        du = subprocess.run(
            ["gcloud", "storage", "du", "-s", "-c", dest_uri],
            capture_output=True,
            text=True,
            check=False,
        )
        if du.returncode != 0 or not du.stdout.strip():
            return False
        parts = du.stdout.strip().split()
        if not parts or not parts[0].isdigit():
            return False
        remote_bytes = int(parts[0])
        return remote_count == local_count and remote_bytes == local_bytes

    def _sync_local(self, source: Path, mirror_root: Path, project: str, dataset_name: str) -> None:
        dest = mirror_root / "projects" / project / "inputs" / dataset_name
        print(f"  Local {source}/ → {dest}/")
        _local_sync(source, dest)
        # Remove .keep placeholder if real files are now present
        keep = dest / ".keep"
        if keep.exists() and any(dest.rglob("*.wav")):
            keep.unlink()


if __name__ == "__main__":
    bucket = bucket_from_env()
    project = (os.environ.get("BMT_PROJECT") or "").strip()
    source_path = (os.environ.get("BMT_SOURCE") or "").strip()
    dataset_name = (os.environ.get("BMT_DATASET_NAME") or "").strip() or None
    force = truthy(os.environ.get("BMT_FORCE"))

    if not project:
        print("::error::Set BMT_PROJECT (e.g. sk)", file=sys.stderr)
        raise SystemExit(1)
    if not source_path:
        print("::error::Set BMT_SOURCE (path to zip or folder)", file=sys.stderr)
        raise SystemExit(1)

    from tools.repo.paths import repo_root

    local_mirror = repo_root() / "gcp" / "remote"
    raise SystemExit(
        BucketUploadDataset().run(
            bucket=bucket,
            project=project,
            source=source_path,
            dataset_name=dataset_name,
            force=force,
            local_mirror=local_mirror,
        )
    )

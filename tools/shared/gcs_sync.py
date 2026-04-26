"""Small Storage-client helpers for recursive bucket sync operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google.cloud import storage

from tools.shared.gcs_storage_client import GcsStorageClientLike


@dataclass(frozen=True, slots=True)
class PrefixStats:
    file_count: int
    total_bytes: int


def iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def upload_tree(
    *,
    client: storage.Client,
    bucket_name: str,
    source_root: Path,
    destination_prefix: str,
    files: list[Path] | None = None,
) -> PrefixStats:
    bucket = client.bucket(bucket_name)
    if files is None:
        files = iter_files(source_root)
    total_bytes = 0
    clean_prefix = destination_prefix.strip("/")
    for path in files:
        rel = path.relative_to(source_root).as_posix()
        blob = bucket.blob(f"{clean_prefix}/{rel}" if clean_prefix else rel)
        blob.upload_from_filename(str(path))
        total_bytes += path.stat().st_size
    return PrefixStats(file_count=len(files), total_bytes=total_bytes)


def sync_tree(
    *,
    client: storage.Client,
    bucket_name: str,
    source_root: Path,
    destination_prefix: str,
) -> PrefixStats:
    files = iter_files(source_root)
    uploaded = upload_tree(
        client=client,
        bucket_name=bucket_name,
        source_root=source_root,
        destination_prefix=destination_prefix,
        files=files,
    )
    bucket = client.bucket(bucket_name)
    clean_prefix = destination_prefix.strip("/")
    local_relative_paths = {path.relative_to(source_root).as_posix() for path in files}
    for blob in client.list_blobs(bucket_name, prefix=clean_prefix):
        if blob.name.endswith("/"):
            continue
        relative = blob.name.removeprefix(f"{clean_prefix}/") if clean_prefix else blob.name
        if relative not in local_relative_paths:
            bucket.blob(blob.name).delete()
    return uploaded


def prefix_stats(*, client: GcsStorageClientLike, bucket_name: str, prefix: str) -> PrefixStats:
    file_count = 0
    total_bytes = 0
    for blob in client.list_blobs(bucket_name, prefix=prefix.strip("/")):
        if blob.name.endswith("/"):
            continue
        file_count += 1
        total_bytes += int(blob.size or 0)
    return PrefixStats(file_count=file_count, total_bytes=total_bytes)

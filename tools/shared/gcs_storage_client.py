"""Structural typing for GCS client operations used by tools (prefix_stats, uploads)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol


class GcsBlobNameSize(Protocol):
    """Blob fields read by :func:`tools.shared.gcs_sync.prefix_stats`."""

    @property
    def name(self) -> str: ...

    @property
    def size(self) -> int | None: ...


class GcsBlobDeletable(Protocol):
    def delete(self) -> None: ...


class GcsBucketWithBlob(Protocol):
    def blob(self, blob_name: str) -> GcsBlobDeletable: ...


class GcsStorageClientLike(Protocol):
    """Subset of ``google.cloud.storage.Client`` used by dataset upload and prefix stats."""

    def bucket(self, bucket_name: str) -> GcsBucketWithBlob: ...

    def list_blobs(
        self,
        bucket_or_name: str,
        *,
        prefix: str | None = None,
    ) -> Iterator[GcsBlobNameSize]: ...

"""Archive importer that expands dataset archives inside GCP."""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from typing import IO, Protocol

from google.cloud import storage as gcs_storage


@dataclass(frozen=True, slots=True)
class DatasetImportRequest:
    source_uri: str
    destination_prefix: str

    @classmethod
    def from_env(cls) -> DatasetImportRequest:
        return cls(
            source_uri=(os.environ.get("BMT_IMPORT_SOURCE_URI") or "").strip(),
            destination_prefix=(os.environ.get("BMT_IMPORT_DEST_PREFIX") or "").strip(),
        )

    def is_ready(self) -> bool:
        return bool(self.source_uri and self.destination_prefix)


class BlobProtocol(Protocol):
    def download_to_filename(self, filename: str) -> None: ...

    def upload_from_file(self, payload: IO[bytes]) -> None: ...

    def delete(self) -> None: ...

    def exists(self) -> bool: ...


class BucketProtocol(Protocol):
    def blob(self, name: str) -> BlobProtocol: ...


class StorageClientProtocol(Protocol):
    def bucket(self, bucket_name: str) -> BucketProtocol: ...


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Unsupported GCS URI: {uri}")
    bucket_name, _, blob_name = uri.removeprefix("gs://").partition("/")
    if not bucket_name or not blob_name:
        raise ValueError(f"Unsupported GCS URI: {uri}")
    return bucket_name, blob_name


class DatasetImporter:
    def __init__(self, client: StorageClientProtocol | None = None) -> None:
        self.client = client or gcs_storage.Client()

    def run(self, *, source_uri: str, destination_prefix: str) -> int:
        bucket_name, blob_name = _parse_gcs_uri(source_uri)
        bucket = self.client.bucket(bucket_name)
        source_blob = bucket.blob(blob_name)

        with tempfile.NamedTemporaryFile(suffix=".zip") as archive_file:
            source_blob.download_to_filename(archive_file.name)
            with zipfile.ZipFile(archive_file.name) as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    dest_name = f"{destination_prefix.rstrip('/')}/{member.filename.lstrip('/')}"
                    dest_blob = bucket.blob(dest_name)
                    if dest_blob.exists():
                        print(f"  [skip] {member.filename} (already uploaded)")  # noqa: T201
                        continue
                    with zf.open(member) as payload:
                        dest_blob.upload_from_file(payload)

        source_blob.delete()
        return 0

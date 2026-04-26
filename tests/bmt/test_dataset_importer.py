from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from runtime.importer import DatasetImporter

pytestmark = pytest.mark.integration


class _FakeBlob:
    def __init__(self, name: str, bucket: _FakeBucket, *, source_file: Path | None = None) -> None:
        self.name = name
        self.bucket = bucket
        self.source_file = source_file
        self.deleted = False
        self.uploaded_bytes: bytes | None = None

    def download_to_filename(self, filename: str) -> None:
        assert self.source_file is not None
        shutil.copy2(self.source_file, filename)

    def upload_from_file(self, payload) -> None:
        data = payload.read()
        assert isinstance(data, bytes)
        self.uploaded_bytes = data
        self.bucket.uploads[self.name] = data

    def exists(self) -> bool:
        return self.name in self.bucket.uploads

    def delete(self) -> None:
        self.deleted = True


class _FakeBucket:
    def __init__(self, archive: Path) -> None:
        self.archive = archive
        self.uploads: dict[str, bytes] = {}
        self.blobs: dict[str, _FakeBlob] = {}

    def blob(self, name: str) -> _FakeBlob:
        if name not in self.blobs:
            source_file = self.archive if name == "imports/dataset.zip" else None
            self.blobs[name] = _FakeBlob(name, self, source_file=source_file)
        return self.blobs[name]


class _FakeClient:
    def __init__(self, archive: Path) -> None:
        self.bucket_obj = _FakeBucket(archive)

    def bucket(self, bucket_name: str) -> _FakeBucket:
        _ = bucket_name
        return self.bucket_obj


def test_dataset_importer_extracts_zip_and_deletes_temp_blob(tmp_path: Path) -> None:
    archive = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("sample.wav", b"fake-wav")
        zf.writestr("nested/other.wav", b"other-wav")

    client = _FakeClient(archive)
    importer = DatasetImporter(client=client)

    rc = importer.run(
        source_uri="gs://demo-bucket/imports/dataset.zip",
        destination_prefix="projects/sk/inputs/false_rejects",
    )

    assert rc == 0
    assert client.bucket_obj.uploads["projects/sk/inputs/false_rejects/sample.wav"] == b"fake-wav"
    assert client.bucket_obj.uploads["projects/sk/inputs/false_rejects/nested/other.wav"] == b"other-wav"
    assert client.bucket_obj.blobs["imports/dataset.zip"].deleted is True

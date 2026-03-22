from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

import pytest

from tools.remote.bucket_upload_dataset import BucketUploadDataset
from tools.shared.gcs_storage_client import GcsBlobNameSize

pytestmark = pytest.mark.unit


class _CloudRunJobResult(TypedDict):
    name: str
    done: bool


class _FakeBlob:
    def __init__(self) -> None:
        self.uploaded_from_filename: str | None = None
        self.deleted = False

    def upload_from_filename(self, filename: str) -> None:
        self.uploaded_from_filename = filename

    def delete(self) -> None:
        self.deleted = True


class _FakeBucket:
    def __init__(self) -> None:
        self.blobs: dict[str, _FakeBlob] = {}

    def blob(self, blob_name: str) -> _FakeBlob:
        self.blobs.setdefault(blob_name, _FakeBlob())
        return self.blobs[blob_name]


class _FakeStorageClient:
    def __init__(self) -> None:
        self.bucket_obj = _FakeBucket()

    def bucket(self, bucket_name: str) -> _FakeBucket:
        return self.bucket_obj

    def list_blobs(self, bucket_or_name: str, *, prefix: str | None = None) -> Iterator[GcsBlobNameSize]:
        return iter(())


def _never_synced(*_args: object, **_kwargs: object) -> bool:
    return False


def test_upload_dataset_uses_import_job_for_archives_when_configured(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("sample.wav", b"fake")

    monkeypatch.setenv("BMT_CONTROL_JOB", "bmt-control")
    monkeypatch.setenv("CLOUD_RUN_REGION", "europe-west4")
    monkeypatch.setenv("GCP_PROJECT", "demo-project")

    fake_client = _FakeStorageClient()
    invocations: list[tuple[str, str, str, dict[str, str]]] = []
    uploads: list[tuple[Path, str]] = []

    def _fake_run_cloud_job(
        *,
        project: str,
        region: str,
        job_name: str,
        env_vars: dict[str, str],
        **_: object,
    ) -> _CloudRunJobResult:
        invocations.append((project, region, job_name, env_vars))
        return {"name": "operations/demo", "done": True}

    def _fake_upload_archive(*, source: Path, destination_uri: str) -> None:
        uploads.append((source, destination_uri))

    monkeypatch.setattr("tools.remote.bucket_upload_dataset.upload_file_to_gcs", _fake_upload_archive)
    monkeypatch.setattr("tools.remote.bucket_upload_dataset.run_cloud_run_job", _fake_run_cloud_job)
    result = BucketUploadDataset(storage_client=fake_client).run(
        bucket="demo-bucket",
        project="sk",
        source=archive,
        dataset_name="false_rejects",
    )

    assert result == 0
    assert len(invocations) == 1
    project, region, job_name, env_vars = invocations[0]
    assert project == "demo-project"
    assert region == "europe-west4"
    assert job_name == "bmt-control"
    assert env_vars["BMT_MODE"] == "dataset-import"
    assert env_vars["BMT_IMPORT_DEST_PREFIX"] == "projects/sk/inputs/false_rejects"
    assert env_vars["GCS_BUCKET"] == "demo-bucket"
    assert env_vars["BMT_IMPORT_SOURCE_URI"].startswith("gs://demo-bucket/imports/sk/sk-false_rejects-")
    assert uploads == [(archive, env_vars["BMT_IMPORT_SOURCE_URI"])]


def test_upload_dataset_uses_gcloud_rsync_for_directories(tmp_path: Path, monkeypatch) -> None:
    dataset_root = tmp_path / "false_rejects"
    dataset_root.mkdir()
    wav_path = dataset_root / "sample.wav"
    wav_path.write_bytes(b"fake")

    rsyncs: list[tuple[Path, str]] = []

    def _fake_rsync_directory(*, source_root: Path, destination_uri: str) -> None:
        rsyncs.append((source_root, destination_uri))

    monkeypatch.setattr("tools.remote.bucket_upload_dataset.sync_directory_to_gcs", _fake_rsync_directory)
    monkeypatch.setattr(BucketUploadDataset, "_already_synced", _never_synced)

    result = BucketUploadDataset(storage_client=_FakeStorageClient()).run(
        bucket="demo-bucket",
        project="sk",
        source=dataset_root,
        dataset_name="false_rejects",
    )

    assert result == 0
    assert rsyncs == [(dataset_root, "gs://demo-bucket/projects/sk/inputs/false_rejects")]

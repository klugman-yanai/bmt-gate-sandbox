"""Thin wrappers around gcloud storage commands used by developer tooling."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from tools.shared.contributor_docs import gcloud_cli_missing_message


class GCloudStorageError(RuntimeError):
    """Raised when a gcloud storage command fails."""


def _gcloud_binary() -> str:
    gcloud = shutil.which("gcloud")
    if gcloud is None:
        raise GCloudStorageError(gcloud_cli_missing_message())
    return gcloud


def _run_storage_command(*args: str) -> None:
    command = [_gcloud_binary(), "storage", *args]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        joined = " ".join(command)
        raise GCloudStorageError(f"command failed with exit code {result.returncode}: {joined}")


def upload_file_to_gcs(*, source: Path, destination_uri: str) -> None:
    _run_storage_command("cp", str(source), destination_uri)


def upload_file_to_gcs_parallel(*, source: Path, destination_uri: str) -> None:
    """Upload a single file using parallel composite uploads (best for files >150 MB)."""
    _run_storage_command("cp", str(source), destination_uri, "--parallel-composite-upload-threshold=150MB")


def sync_directory_to_gcs(*, source_root: Path, destination_uri: str) -> None:
    _run_storage_command(
        "rsync",
        str(source_root),
        destination_uri,
        "--recursive",
        "--delete-unmatched-destination-objects",
    )

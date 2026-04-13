#!/usr/bin/env python3
"""Upload a WAV dataset (zip or folder) to the canonical project inputs path.

GCS destination:  gs://<bucket>/projects/<project>/inputs/<dataset>/
Local mirror:     gcp/stage/projects/<project>/inputs/<dataset>/  (opt-in only)

Archives are always imported via Cloud Run (BMT_CONTROL_JOB + CLOUD_RUN_REGION +
GCP_PROJECT required). The Cloud Run job downloads the zip from a staging prefix,
extracts it in-memory, and writes members to the destination — no local disk needed
regardless of archive size.

Directories upload with ``gcloud storage rsync``.

Dataset name is auto-detected from the source filename/directory when not
supplied: ``sk_false_rejects.zip`` → ``false_rejects`` (project prefix
stripped if present).
"""

from __future__ import annotations

import shutil
import sys
import time
import zipfile
from pathlib import Path

from google.cloud import storage

from gcp.image.config.constants import (
    ENV_BMT_CONTROL_JOB,
    ENV_BMT_DATASET_TRANSFER_JOB,
    ENV_CLOUD_RUN_REGION,
    ENV_GCP_PROJECT,
    ENV_GCS_BUCKET,
)
from tools.remote.gen_input_manifest import GenInputManifest
from tools.shared.bucket_env import bucket_from_env, bucket_root_uri, truthy
from tools.shared.gcloud_storage import GCloudStorageError, sync_directory_to_gcs, upload_file_to_gcs, upload_file_to_gcs_parallel
from tools.shared.gcs_storage_client import GcsStorageClientLike
from tools.shared.gcs_sync import prefix_stats
from tools.shared.google_api import GoogleApiError, run_cloud_run_job
from tools.shared.repo_vars import repo_var
from tools.shared.rich_minimal import spinner_status, step_console, success_panel


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


def _is_zip(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".zip"


def _zip_stats(archive: Path) -> tuple[int, int]:
    """Return (member_count, total_uncompressed_bytes) from zip central directory."""
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        return len(members), sum(m.file_size for m in members)


def _dir_stats(source: Path) -> tuple[int, int]:
    """Return (file_count, total_bytes) for a directory tree."""
    files = [p for p in source.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def _fmt_bytes(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    return f"{n / 1_000:.1f} KB"


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def _control_job_name() -> str:
    return (repo_var(ENV_BMT_CONTROL_JOB) or repo_var("BMT_DATASET_IMPORT_JOB")).strip()


def _cloud_run_region() -> str:
    return repo_var(ENV_CLOUD_RUN_REGION)


def _gcp_project() -> str:
    return repo_var(ENV_GCP_PROJECT)


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

    def __init__(self, *, storage_client: GcsStorageClientLike | None = None) -> None:
        self.storage_client: GcsStorageClientLike = storage_client or storage.Client()

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
            print(f"::error::Set {ENV_GCS_BUCKET} (or pass --bucket)", file=sys.stderr)
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

        # Pre-flight summary
        console = step_console()
        if _is_zip(src):
            file_count, total_bytes = _zip_stats(src)
            mode = "cloud-import  (zip staged to imports/ → Cloud Run extraction)"
        elif src.is_dir():
            file_count, total_bytes = _dir_stats(src)
            mode = "rsync"
        else:
            print(f"::error::Source is neither a directory nor a .zip archive: {src}", file=sys.stderr)
            return 1

        if console:
            from rich.table import Table

            table = Table.grid(padding=(0, 2))
            table.add_row("[bold]Dataset[/]", name)
            table.add_row("[bold]Source[/]", f"{src.name}  →  {file_count} files · {_fmt_bytes(total_bytes)}")
            table.add_row("[bold]Dest[/]", gcs_dest + "/")
            table.add_row("[bold]Mode[/]", mode)
            console.print(table)
            console.print()
        else:
            print(f"Dataset  {name}")
            print(f"Source   {src.name}  →  {file_count} files · {_fmt_bytes(total_bytes)}")
            print(f"Dest     {gcs_dest}/")
            print(f"Mode     {mode}")

        start = time.monotonic()

        if src.is_dir():
            rc = self._upload(
                source=src,
                gcs_dest=gcs_dest,
                local_mirror=local_mirror,
                project=project,
                dataset_name=name,
                force=force,
            )
        else:
            # Archive: Cloud Run import only
            if not self._can_use_import_job():
                missing = [
                    v for v in (ENV_BMT_CONTROL_JOB, ENV_CLOUD_RUN_REGION, ENV_GCP_PROJECT) if not repo_var(v).strip()
                ]
                print(
                    "::error::Archives require the Cloud Run import job, but the following vars are not set: "
                    + ", ".join(missing),
                    file=sys.stderr,
                )
                print(
                    "  Extract the archive manually and pass the directory as source, "
                    "or configure the missing repo vars.",
                    file=sys.stderr,
                )
                return 1
            rc = self._dispatch_import_job(
                bucket=bucket,
                project=project,
                source=src,
                dataset_name=name,
            )

        if rc == 0:
            self._validate_upload(gcs_dest=gcs_dest, expected_count=file_count, expected_bytes=total_bytes)
            self._regen_manifest(bucket=bucket, project=project, dataset_name=name, local_mirror=local_mirror)
            elapsed = time.monotonic() - start
            summary = f"{name} · {file_count} files · {_fmt_bytes(total_bytes)} · {_fmt_elapsed(elapsed)}\n{gcs_dest}/"
            success_panel(console, "Upload complete", summary)

        return rc

    def _can_use_import_job(self) -> bool:
        return bool(_control_job_name() and _cloud_run_region() and _gcp_project())

    def _dispatch_import_job(
        self,
        *,
        bucket: str,
        project: str,
        source: Path,
        dataset_name: str,
    ) -> int:
        import uuid

        import_job = _control_job_name()
        region = _cloud_run_region()
        gcp_project = _gcp_project()
        if not import_job or not region or not gcp_project:
            return 1

        archive_name = f"{project}-{dataset_name}-{uuid.uuid4().hex}{source.suffix.lower()}"
        temp_archive_prefix = f"imports/{project}"
        temp_archive_object = f"{temp_archive_prefix}/{archive_name}"
        temp_archive_uri = f"{bucket_root_uri(bucket)}/{temp_archive_object}"
        dest_prefix = f"projects/{project}/inputs/{dataset_name}"
        print(f"Staging archive → {temp_archive_uri}")
        try:
            upload_file_to_gcs(source=source, destination_uri=temp_archive_uri)
        except GCloudStorageError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1

        print(f"Dispatching Cloud Run import job {import_job!r}…")
        try:
            console = step_console()
            with spinner_status(console, f"Cloud Run job {import_job!r} running…"):
                run_cloud_run_job(
                    project=gcp_project,
                    region=region,
                    job_name=import_job,
                    env_vars={
                        "BMT_MODE": "dataset-import",
                        "BMT_IMPORT_SOURCE_URI": temp_archive_uri,
                        "BMT_IMPORT_DEST_PREFIX": dest_prefix,
                        ENV_GCS_BUCKET: bucket,
                    },
                )
        except GoogleApiError as exc:
            self.storage_client.bucket(bucket).blob(temp_archive_object).delete()
            print(f"::error::{exc}", file=sys.stderr)
            return 1

        return 0

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

        print(f"  gcloud storage rsync {source}/ → {gcs_dest}/")
        try:
            sync_directory_to_gcs(source_root=source, destination_uri=gcs_dest)
        except GCloudStorageError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1

        if local_mirror:
            self._sync_local(source, local_mirror, project, dataset_name)

        n_files = sum(1 for _ in source.rglob("*") if _.is_file())
        print(f"Synced {n_files} file(s) to {gcs_dest}/")
        return 0

    def _validate_upload(self, *, gcs_dest: str, expected_count: int, expected_bytes: int) -> None:
        bucket_name, prefix = self._split_gs_uri(gcs_dest)
        actual = prefix_stats(client=self.storage_client, bucket_name=bucket_name, prefix=prefix)
        if actual.file_count != expected_count or actual.total_bytes != expected_bytes:
            print(
                f"Warning: GCS has {actual.file_count} files / {_fmt_bytes(actual.total_bytes)} "
                f"but expected {expected_count} files / {_fmt_bytes(expected_bytes)}",
                file=sys.stderr,
            )
        else:
            print(f"Verified: {actual.file_count} files / {_fmt_bytes(actual.total_bytes)} in GCS.")

    def _regen_manifest(
        self,
        *,
        bucket: str,
        project: str,
        dataset_name: str,
        local_mirror: Path | None,
    ) -> None:
        import tempfile

        print("Regenerating dataset manifest…")
        if local_mirror is not None:
            GenInputManifest().run(
                bucket=bucket,
                project=project,
                dataset=dataset_name,
                stage_root=local_mirror,
                upload_to_gcs=True,
            )
        else:
            with tempfile.TemporaryDirectory() as tmp:
                GenInputManifest().run(
                    bucket=bucket,
                    project=project,
                    dataset=dataset_name,
                    stage_root=tmp,
                    upload_to_gcs=True,
                )

    def _already_synced(self, source: Path, dest_uri: str) -> bool:
        local_files = [p for p in source.rglob("*") if p.is_file()]
        if not local_files:
            return False
        local_count = len(local_files)
        local_bytes = sum(p.stat().st_size for p in local_files)
        bucket_name, prefix = self._split_gs_uri(dest_uri)
        remote_stats = prefix_stats(client=self.storage_client, bucket_name=bucket_name, prefix=prefix)
        return remote_stats.file_count == local_count and remote_stats.total_bytes == local_bytes

    def _sync_local(self, source: Path, mirror_root: Path, project: str, dataset_name: str) -> None:
        dest = mirror_root / "projects" / project / "inputs" / dataset_name
        print(f"  Local {source}/ → {dest}/")
        _local_sync(source, dest)
        # Remove .keep placeholder if real files are now present
        keep = dest / ".keep"
        if keep.exists() and any(dest.rglob("*.wav")):
            keep.unlink()

    @staticmethod
    def _split_gs_uri(uri: str) -> tuple[str, str]:
        clean_uri = uri.removeprefix("gs://")
        bucket_name, _, prefix = clean_uri.partition("/")
        if not bucket_name:
            raise ValueError(f"Invalid GCS destination: {uri}")
        return bucket_name, prefix.strip("/")


if __name__ == "__main__":
    import os

    bucket = bucket_from_env()
    project = os.environ.get("BMT_PROJECT", "").strip()
    source_path = os.environ.get("BMT_SOURCE", "").strip()
    dataset_name = os.environ.get("BMT_DATASET_NAME", "").strip() or None
    force = truthy(os.environ.get("BMT_FORCE"))

    if not project:
        print("::error::Set BMT_PROJECT (e.g. sk)", file=sys.stderr)
        raise SystemExit(1)
    if not source_path:
        print("::error::Set BMT_SOURCE (path to zip or folder)", file=sys.stderr)
        raise SystemExit(1)

    from tools.repo.paths import repo_root

    local_str = os.environ.get("BMT_LOCAL_MIRROR", "").strip()
    local_mirror = repo_root() / "gcp" / "stage" if truthy(local_str) else None
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

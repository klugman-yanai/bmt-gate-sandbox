#!/usr/bin/env python3
"""Generate dataset_manifest.json for a project/dataset input prefix in GCS.

Enumerates objects under gs://<bucket>/projects/<project>/inputs/<dataset>/
using ``gcloud storage ls --json``, normalises paths, and writes
``dataset_manifest.json`` to the local staging area at:

    gcp/stage/projects/<project>/inputs/<dataset>/dataset_manifest.json

The manifest is tracked in git so any clone gives the full directory tree shape
without the actual audio files (offline manifest-only visibility).

Usage (env or flags):
    GCS_BUCKET=my-bucket BMT_PROJECT=sk BMT_DATASET=false_rejects \\
        uv run python -m tools.remote.gen_input_manifest

    uv run python -m tools.remote.gen_input_manifest \\
        --project sk --dataset false_rejects
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from whenever import Instant

from tools.repo.paths import DEFAULT_STAGE_ROOT
from tools.shared.bucket_env import bucket_from_env, bucket_root_uri
from tools.shared.dataset_manifest import DatasetEntry, DatasetManifest


def _gcs_ls_json(uri: str) -> list[dict[str, object]]:
    """List GCS objects under uri using gcloud storage ls --json."""
    proc = subprocess.run(
        ["gcloud", "storage", "ls", "--json", uri],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gcloud storage ls --json {uri} failed: {(proc.stderr or proc.stdout or '').strip()}"
        )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse gcloud output as JSON: {exc}") from exc
    if not isinstance(result, list):
        raise RuntimeError(f"Expected JSON array from gcloud ls, got: {type(result)}")
    return result  # type: ignore[return-value]


def _entry_from_gcs_object(obj: dict[str, object], prefix: str) -> DatasetEntry | None:
    """Convert a gcloud storage ls --json object to a DatasetEntry."""
    url = str(obj.get("url", "")).strip()
    if not url:
        return None
    # Strip the gs://bucket/prefix/ portion to get the relative name.
    # url is like gs://bucket/projects/sk/inputs/false_rejects/ambient/file.wav
    prefix_uri = prefix.rstrip("/") + "/"
    if prefix_uri in url:
        name = url[url.index(prefix_uri) + len(prefix_uri) :]
    else:
        # Fallback: strip everything up to and including the last slash of the prefix
        name = url.rsplit(prefix.rstrip("/"), 1)[-1].lstrip("/")

    if not name or name.endswith("/"):
        return None  # skip directory markers

    size = int(str(obj.get("size", 0)))
    # GCS ls --json returns md5Hash not sha256; use empty sha256 as placeholder
    sha256 = str(obj.get("etag", "")).strip() or ""
    updated = str(obj.get("updated", "")).strip()

    return DatasetEntry(name=name, size_bytes=size, sha256=sha256, updated=updated)


class GenInputManifest:
    """Generate dataset_manifest.json for a project/dataset prefix."""

    def run(
        self,
        *,
        bucket: str,
        project: str,
        dataset: str,
        stage_root: Path | str = DEFAULT_STAGE_ROOT,
        dry_run: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1
        if not project:
            print("::error::project is required (e.g. sk)", file=sys.stderr)
            return 1
        if not dataset:
            print("::error::dataset is required (e.g. false_rejects)", file=sys.stderr)
            return 1

        prefix = f"projects/{project}/inputs/{dataset}"
        gcs_uri = f"{bucket_root_uri(bucket)}/{prefix}/"
        print(f"Enumerating {gcs_uri}")

        try:
            objects = _gcs_ls_json(gcs_uri)
        except RuntimeError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1

        entries: list[DatasetEntry] = []
        for obj in objects:
            entry = _entry_from_gcs_object(obj, prefix)
            if entry is not None:
                entries.append(entry)

        entries.sort(key=lambda e: e.name)
        manifest = DatasetManifest(
            schema_version=1,
            project=project,
            dataset=dataset,
            bucket=bucket,
            prefix=prefix,
            generated_at=Instant.now().format_iso(unit="second"),
            files=tuple(entries),
        )

        out_path = Path(stage_root) / prefix / "dataset_manifest.json"
        print(f"Dataset: {project}/{dataset}")
        print(f"Files:   {len(entries)}")
        print(f"Output:  {out_path}")

        if dry_run:
            print("(dry-run; not writing)")
            return 0

        manifest.write(out_path)
        print("Manifest written. Commit dataset_manifest.json to track the dataset.")
        return 0


if __name__ == "__main__":
    _bucket = bucket_from_env()
    _project = (os.environ.get("BMT_PROJECT") or "").strip()
    _dataset = (os.environ.get("BMT_DATASET") or "").strip()
    _stage = (os.environ.get("BMT_STAGE_ROOT") or "").strip() or DEFAULT_STAGE_ROOT
    _dry_run = bool((os.environ.get("BMT_DRY_RUN") or "").strip())
    raise SystemExit(
        GenInputManifest().run(
            bucket=_bucket,
            project=_project,
            dataset=_dataset,
            stage_root=_stage,
            dry_run=_dry_run,
        )
    )

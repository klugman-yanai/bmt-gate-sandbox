#!/usr/bin/env python3
"""Sync a single staged project subtree to the bucket."""

from __future__ import annotations

import sys
from pathlib import Path

from google.cloud import storage

from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root
from tools.shared.bucket_env import bucket_root_uri
from tools.shared.gcs_sync import sync_tree


class BucketSyncProject:
    def __init__(self, *, storage_client: storage.Client | None = None) -> None:
        self.storage_client = storage_client or storage.Client()

    def run(self, *, bucket: str, project: str, stage_root: Path | str | None = None) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        root = Path(stage_root) if stage_root is not None else repo_root() / DEFAULT_STAGE_ROOT
        src = root / "projects" / project
        if not src.is_dir():
            print(f"::error::Missing staged project directory: {src}", file=sys.stderr)
            return 1

        dest = f"{bucket_root_uri(bucket)}/projects/{project}"
        print(f"Syncing staged project {src}/ -> {dest}/")
        sync_tree(
            client=self.storage_client,
            bucket_name=bucket,
            source_root=src,
            destination_prefix=f"projects/{project}",
        )
        return 0

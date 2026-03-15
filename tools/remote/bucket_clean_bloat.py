#!/usr/bin/env python3
"""Remove Python/uv bloat objects from GCS bucket.

Lists objects under bucket root, filters by bloat patterns, deletes. Default dry-run.
Pass --execute to perform deletions. Run from repo root with GCS_BUCKET set.
"""

from __future__ import annotations

import subprocess
import sys

from tools.shared.bucket_env import (
    bucket_from_env,
    bucket_root_uri,
)
from tools.shared.bucket_sync import matches
from tools.shared.layout_patterns import BLOAT_PATTERNS

BATCH_SIZE = 500  # URIs per gcloud storage rm call to avoid argv length limits


def _list_uris(prefix_uri: str) -> list[str]:
    """List all object URIs under prefix (recursive)."""
    proc = subprocess.run(
        ["gcloud", "storage", "ls", prefix_uri.rstrip("/") + "/", "--recursive"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "").strip()
    uris = [line.strip() for line in out.splitlines() if line.strip()]
    if proc.returncode != 0 and not uris:
        no_match = "One or more URLs matched no objects" in (proc.stderr or "")
        if not no_match:
            raise RuntimeError(f"gcloud storage ls failed: {proc.stderr or proc.stdout}")
    return uris


def _rel_path(uri: str, prefix_uri: str) -> str:
    """Object path relative to prefix (no gs://bucket/prefix/)."""
    base = prefix_uri.rstrip("/") + "/"
    if not uri.startswith(base):
        return uri
    return uri[len(base) :]


def _filter_bloat(uris: list[str], prefix_uri: str, patterns: tuple[str, ...]) -> list[str]:
    return [u for u in uris if matches(patterns, _rel_path(u, prefix_uri))]


def _delete_uris(uris: list[str], dry_run: bool) -> None:
    if not uris:
        return
    if dry_run:
        for u in uris:
            print(f"  [dry-run] would remove: {u}")
        return
    for i in range(0, len(uris), BATCH_SIZE):
        batch = uris[i : i + BATCH_SIZE]
        subprocess.run(
            ["gcloud", "storage", "rm", "--quiet", *batch],
            check=True,
        )


class BucketCleanBloat:
    """Remove Python/uv bloat from GCS bucket."""

    def run(
        self,
        *,
        bucket: str,
        dry_run: bool = True,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        prefix_uri = bucket_root_uri(bucket)
        print(f"Listing bucket: {prefix_uri}")
        uris = _list_uris(prefix_uri)
        bloat = _filter_bloat(uris, prefix_uri, BLOAT_PATTERNS)
        if not bloat:
            print("  No bloat objects found.")
        else:
            print(f"  Found {len(bloat)} bloat object(s) to remove.")
            _delete_uris(bloat, dry_run=dry_run)
        total_removed = len(bloat)

        if dry_run:
            if total_removed:
                print(f"Would remove {total_removed} object(s). Run with --execute to perform deletions.")
            else:
                print("No bloat objects found.")
        else:
            print(f"Removed {total_removed} object(s).")
        return 0


if __name__ == "__main__":
    bucket = bucket_from_env()
    dry_run = "--execute" not in sys.argv
    raise SystemExit(BucketCleanBloat().run(bucket=bucket, dry_run=dry_run))

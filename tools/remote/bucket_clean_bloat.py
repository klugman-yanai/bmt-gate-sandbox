#!/usr/bin/env python3
"""Remove Python/uv bloat objects from GCS code (and optionally runtime) namespace.

Lists objects under the chosen prefix(es), filters by the same bloat patterns used
by bucket_sync_gcp and bucket_sync_runtime_seed, and deletes them. Default is dry-run (no deletions).
Use BMT_EXECUTE=1 to perform deletions. Run from repo root with GCS_BUCKET set.
"""

from __future__ import annotations

import os
import subprocess
import sys

from tools.shared.bucket_env import (
    bucket_from_env,
    code_bucket_root_uri,
    runtime_bucket_root_uri,
    truthy,
)
from tools.shared.bucket_sync import matches
from tools.shared.layout_patterns import BLOAT_PATTERNS, CODE_CLEAN_PATTERNS

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
    """Remove Python/uv bloat from GCS code and/or runtime namespace."""

    def run(
        self,
        *,
        bucket: str,
        scope: str = "code",
        dry_run: bool = True,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        if scope not in ("code", "runtime", "both"):
            print("::error::BMT_CLEAN_SCOPE must be code, runtime, or both", file=sys.stderr)
            return 1

        to_clean: list[tuple[str, tuple[str, ...]]] = []
        if scope in ("code", "both"):
            to_clean.append((code_bucket_root_uri(bucket), CODE_CLEAN_PATTERNS))
        if scope in ("runtime", "both"):
            to_clean.append((runtime_bucket_root_uri(bucket), BLOAT_PATTERNS))

        total_removed = 0
        for prefix_uri, patterns in to_clean:
            label = "code" if "code" in prefix_uri else "runtime"
            print(f"Listing {label} namespace: {prefix_uri}")
            uris = _list_uris(prefix_uri)
            bloat = _filter_bloat(uris, prefix_uri, patterns)
            if not bloat:
                print(f"  No bloat objects under {prefix_uri}")
                continue
            print(f"  Found {len(bloat)} bloat object(s) to remove.")
            _delete_uris(bloat, dry_run=dry_run)
            total_removed += len(bloat)

        if dry_run:
            if total_removed:
                print(f"Would remove {total_removed} object(s). Run with BMT_EXECUTE=1 to perform deletions.")
            else:
                print("No bloat objects found.")
        else:
            print(f"Removed {total_removed} object(s).")
        return 0


if __name__ == "__main__":
    bucket = bucket_from_env()
    scope = (os.environ.get("BMT_CLEAN_SCOPE") or "").strip() or "code"
    dry_run = not truthy(os.environ.get("BMT_EXECUTE"))
    raise SystemExit(BucketCleanBloat().run(bucket=bucket, scope=scope, dry_run=dry_run))

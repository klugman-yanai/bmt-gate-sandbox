#!/usr/bin/env python3
"""Pre-flight: diff bucket code/ listing vs gcp/image and report.

Reads a saved preflight report (from preflight_bucket_vs_remote.sh) or runs
gcloud to list gs://BUCKET/code/, then lists gcp/image files and reports:
- In bucket but not in gcp/image (would be dropped when code leaves bucket)
- In gcp/image but not in bucket (expected if never synced or excluded)

Usage:
  GCS_BUCKET=<bucket> uv run python tools/scripts/preflight_bucket_vs_remote.py
  uv run python tools/scripts/preflight_bucket_vs_remote.py --report .local/preflight-bucket-YYYYMMDD-HHMMSS.txt
  uv run python tools/scripts/preflight_bucket_vs_remote.py --local-only   # only list gcp/image, no gcloud
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from tools.shared.bucket_sync import matches
from tools.shared.layout_patterns import DEFAULT_CODE_EXCLUDES


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root


def _gcp_image_files(repo_root: Path) -> set[str]:
    """Return relative paths under gcp/image that are not excluded by code sync."""
    image_root = repo_root / "gcp" / "image"
    if not image_root.is_dir():
        return set()
    out: set[str] = set()
    for p in image_root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(image_root).as_posix()
        if matches(DEFAULT_CODE_EXCLUDES, rel):
            continue
        out.add(rel)
    return out


def _parse_code_listing_from_report(report_path: Path) -> set[str] | None:
    """Extract object paths under code/ from a preflight report (section 2)."""
    text = report_path.read_text()
    in_section = False
    paths: set[str] = set()
    for line in text.splitlines():
        if "=== 2) All objects under code/" in line:
            in_section = True
            continue
        if in_section:
            if line.strip().startswith("==="):
                break
            # gcloud storage ls -r outputs full URIs like gs://bucket/code/scripts/foo.sh
            if "gs://" in line:
                m = re.search(r"gs://[^/]+/code/(.+)$", line.strip())
                if m:
                    paths.add(m.group(1).rstrip("/"))
    return paths or None


def _fetch_bucket_code_listing(bucket: str) -> set[str]:
    """Run gcloud storage ls -r gs://bucket/code/ and return relative paths."""
    proc = subprocess.run(
        ["gcloud", "storage", "ls", "-r", f"gs://{bucket}/code/"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    paths: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if "gs://" in line:
            m = re.search(r"gs://[^/]+/code/(.+)$", line)
            if m:
                paths.add(m.group(1).rstrip("/"))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flight: diff bucket code/ vs gcp/image")
    parser.add_argument("--report", type=Path, help="Path to saved preflight report (.txt)")
    parser.add_argument("--local-only", action="store_true", help="Only list gcp/image, no gcloud")
    args = parser.parse_args()
    repo_root = _repo_root()
    image_paths = _gcp_image_files(repo_root)
    print(f"gcp/image files (excludes sync-excluded): {len(image_paths)}")
    if args.local_only:
        for p in sorted(image_paths):
            print(p)
        return 0
    bucket = (os.environ.get("GCS_BUCKET") or "").strip()
    if args.report:
        if not args.report.is_file():
            print(f"::error::Report not found: {args.report}", file=sys.stderr)
            return 1
        bucket_paths = _parse_code_listing_from_report(args.report)
        if bucket_paths is None:
            print("::error::No code/ listing found in report (run preflight_bucket_vs_remote.sh first)", file=sys.stderr)
            return 1
    else:
        if not bucket:
            print("::error::Set GCS_BUCKET or pass --report", file=sys.stderr)
            return 1
        bucket_paths = _fetch_bucket_code_listing(bucket)
    print(f"Bucket gs://{bucket or 'report'}/code/ objects: {len(bucket_paths)}")
    in_bucket_not_image = bucket_paths - image_paths
    in_image_not_bucket = image_paths - bucket_paths
    if in_bucket_not_image:
        print("\nIn bucket code/ but NOT in gcp/image (would be dropped when code leaves bucket):")
        for p in sorted(in_bucket_not_image)[:50]:
            print(f"  {p}")
        if len(in_bucket_not_image) > 50:
            print(f"  ... and {len(in_bucket_not_image) - 50} more")
    else:
        print("\nAll bucket code/ paths have a counterpart in gcp/image.")
    if in_image_not_bucket:
        print("\nIn gcp/image but NOT in bucket (ok if never synced or excluded):")
        for p in sorted(in_image_not_bucket)[:50]:
            print(f"  {p}")
        if len(in_image_not_bucket) > 50:
            print(f"  ... and {len(in_image_not_bucket) - 50} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

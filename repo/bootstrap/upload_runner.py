#!/usr/bin/env python3
"""Upload runner with single previous-version rotation + metadata."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=capture)


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--bucket", default=os.environ.get("BUCKET") or os.environ.get("GCS_BUCKET", "")
    )
    _ = parser.add_argument(
        "--bucket-prefix", default=os.environ.get("BMT_BUCKET_PREFIX", "")
    )
    _ = parser.add_argument(
        "--runner-path",
        default="repo/staging/runners/sk_gcc_release/kardome_runner",
    )
    _ = parser.add_argument("--runner-uri", default="sk/runners/sk_gcc_release/kardome_runner")
    _ = parser.add_argument("--source", default="sandbox_manual")
    _ = parser.add_argument("--source-ref", default=os.environ.get("SOURCE_REF", ""))
    _ = parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.bucket:
        print("::error::Set BUCKET (or GCS_BUCKET)", file=sys.stderr)
        return 1

    runner_path = Path(args.runner_path)
    if not runner_path.is_file():
        print(f"::error::Runner file not found: {runner_path}", file=sys.stderr)
        return 1

    source_ref = args.source_ref
    if not source_ref:
        proc = run(["git", "rev-parse", "--short", "HEAD"], capture=True)
        source_ref = proc.stdout.strip() if proc.returncode == 0 else "unknown"

    prefix = args.bucket_prefix.strip("/")
    runner_uri = args.runner_uri.lstrip("/")
    bucket_root = f"gs://{args.bucket}/{prefix}" if prefix else f"gs://{args.bucket}"
    canonical_uri = f"{bucket_root}/{runner_uri}"
    previous_uri = f"{canonical_uri}.previous"
    meta_uri = (
        f"{bucket_root}/{Path(runner_uri).parent.as_posix()}/runner_latest_meta.json"
    )

    local_size = runner_path.stat().st_size

    remote_exists = run(["gcloud", "storage", "ls", canonical_uri]).returncode == 0
    remote_size = None
    if remote_exists:
        details = run(["gcloud", "storage", "ls", "-L", canonical_uri], capture=True)
        if details.returncode == 0:
            for line in details.stdout.splitlines():
                if "Content-Length:" in line:
                    value = line.split(":", 1)[1].strip().replace(",", "")
                    if value.isdigit():
                        remote_size = int(value)
                    break

    if (
        (not args.force)
        and remote_exists
        and remote_size is not None
        and remote_size == local_size
    ):
        print(
            f"Runner appears unchanged (size={local_size}); skipping upload. Use --force to override."
        )
        return 0

    if remote_exists:
        cp_prev = run(
            ["gcloud", "storage", "cp", canonical_uri, previous_uri, "--quiet"]
        )
        if cp_prev.returncode != 0:
            return cp_prev.returncode
        print(f"Rotated previous runner to {previous_uri}")

    cp_new = run(
        ["gcloud", "storage", "cp", str(runner_path), canonical_uri, "--quiet"]
    )
    if cp_new.returncode != 0:
        return cp_new.returncode

    meta = {
        "uploaded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": args.source,
        "source_ref": source_ref,
        "size_bytes": local_size,
        "bucket_path": canonical_uri,
    }

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
        json.dump(meta, tmp, indent=2)
        _ = tmp.write("\n")
        tmp_path = Path(tmp.name)

    try:
        cp_meta = run(["gcloud", "storage", "cp", str(tmp_path), meta_uri, "--quiet"])
        if cp_meta.returncode != 0:
            return cp_meta.returncode
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"Uploaded runner to {canonical_uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

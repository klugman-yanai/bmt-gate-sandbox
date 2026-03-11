#!/usr/bin/env python3
"""Verify local gcp/code matches the manifest uploaded to code/_meta/remote_manifest.json."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tools.repo.paths import DEFAULT_CONFIG_ROOT
from tools.shared.bucket_env import bucket_from_env, code_bucket_root_uri, truthy
from tools.shared.bucket_sync import download_manifest, local_digest
from tools.shared.layout_patterns import DEFAULT_CODE_EXCLUDES


class BucketVerifyGcpSync:
    """Verify local gcp/code matches the manifest uploaded to code/_meta/remote_manifest.json."""

    def run(
        self,
        *,
        bucket: str,
        src_dir: str = DEFAULT_CONFIG_ROOT,
        include_runtime_artifacts: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        src = Path(src_dir)
        if not src.is_dir():
            print(f"::error::Missing source directory: {src}", file=sys.stderr)
            return 1

        code_root = code_bucket_root_uri(bucket)
        manifest_uri = f"{code_root}/_meta/remote_manifest.json"
        local_d, local_count = local_digest(src, include_runtime_artifacts, DEFAULT_CODE_EXCLUDES)
        manifest = download_manifest(manifest_uri, required=True)

        remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
        remote_count = int(manifest.get("source_file_count", -1))
        if not remote_digest:
            print(f"::error::Manifest missing source_digest_sha256: {manifest_uri}", file=sys.stderr)
            return 1

        if local_d != remote_digest or local_count != remote_count:
            print(f"::error::gcp/code is not in sync with {manifest_uri}", file=sys.stderr)
            print(
                f"Local digest={local_d} count={local_count}; manifest digest={remote_digest} count={remote_count}",
                file=sys.stderr,
            )
            return 1

        print(f"Verified code mirror sync against {manifest_uri}")
        print(f"Digest: {local_d}")
        print(f"File count: {local_count}")
        return 0


if __name__ == "__main__":
    import os

    bucket = bucket_from_env()
    src_dir = (os.environ.get("BMT_SRC_DIR") or "").strip() or DEFAULT_CONFIG_ROOT
    include = truthy(os.environ.get("BMT_INCLUDE_RUNTIME_ARTIFACTS"))
    raise SystemExit(
        BucketVerifyGcpSync().run(
            bucket=bucket,
            src_dir=src_dir,
            include_runtime_artifacts=include,
        )
    )

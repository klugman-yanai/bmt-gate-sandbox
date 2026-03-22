#!/usr/bin/env python3
"""Verify local gcp/stage matches runtime seed manifest in bucket."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from tools.repo.paths import DEFAULT_STAGE_ROOT
from tools.shared.bucket_env import bucket_from_env, runtime_bucket_root_uri, truthy
from tools.shared.bucket_sync import download_manifest, local_digest
from tools.shared.layout_patterns import FORBIDDEN_RUNTIME_SEED

RUNTIME_SEED_MANIFEST = "_meta/runtime_seed_manifest.json"


class BucketVerifyRuntimeSeedSync:
    """Verify local gcp/stage matches runtime seed manifest in bucket."""

    def run(
        self,
        *,
        bucket: str,
        src_dir: Path | str = DEFAULT_STAGE_ROOT,
        allow_generated_artifacts: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        src = Path(src_dir)
        if not src.is_dir():
            print(f"::error::Missing source directory: {src}", file=sys.stderr)
            return 1

        manifest_uri = f"{runtime_bucket_root_uri(bucket)}/{RUNTIME_SEED_MANIFEST}"
        local_d, local_count = local_digest(src, allow_generated_artifacts, FORBIDDEN_RUNTIME_SEED)

        try:
            manifest = download_manifest(manifest_uri, required=True)
        except RuntimeError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1

        assert manifest is not None
        remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
        remote_count = int(str(manifest.get("source_file_count", -1)))
        if not remote_digest:
            print(f"::error::Runtime seed manifest missing source_digest_sha256: {manifest_uri}", file=sys.stderr)
            return 1

        if local_d != remote_digest or local_count != remote_count:
            print(f"::error::gcp/stage is not in sync with {manifest_uri}", file=sys.stderr)
            print(
                f"Local digest={local_d} count={local_count}; manifest digest={remote_digest} count={remote_count}",
                file=sys.stderr,
            )
            return 1

        print(f"Verified runtime seed sync against {manifest_uri}")
        print(f"Digest: {local_d}")
        print(f"File count: {local_count}")
        return 0


if __name__ == "__main__":
    import os

    bucket = bucket_from_env()
    src_dir = (os.environ.get("BMT_SRC_DIR") or "").strip() or DEFAULT_STAGE_ROOT
    allow = truthy(os.environ.get("BMT_ALLOW_GENERATED_ARTIFACTS"))
    raise SystemExit(
        BucketVerifyRuntimeSeedSync().run(
            bucket=bucket,
            src_dir=src_dir,
            allow_generated_artifacts=allow,
        )
    )

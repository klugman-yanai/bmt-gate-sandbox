#!/usr/bin/env python3
"""Upload runner with single previous-version rotation + metadata.

Default runner-path and runner-uri are for the current sk project; override via
env for other projects.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from whenever import Instant

from tools.shared.bucket_env import bucket_from_env, bucket_root_uri, truthy


def _run_cmd(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=capture)


class BucketUploadRunner:
    """Upload runner with single previous-version rotation + metadata."""

    def run(
        self,
        *,
        bucket: str,
        runner_path: Path | str = "repo/staging/runners/sk_gcc_release/kardome_runner",
        runner_uri: str = "sk/runners/sk_gcc_release/kardome_runner",
        source: str = "sandbox_manual",
        source_ref: str = "",
        force: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        runner = Path(runner_path)
        if not runner.is_file():
            print(f"::error::Runner file not found: {runner}", file=sys.stderr)
            return 1

        if not source_ref:
            proc = _run_cmd(["git", "rev-parse", "--short", "HEAD"], capture=True)
            source_ref = proc.stdout.strip() if proc.returncode == 0 else "unknown"

        bucket_root = bucket_root_uri(bucket)
        runner_uri_clean = runner_uri.lstrip("/")
        canonical_uri = f"{bucket_root}/{runner_uri_clean}"
        previous_uri = f"{canonical_uri}.previous"
        meta_uri = f"{bucket_root}/{Path(runner_uri_clean).parent.as_posix()}/runner_latest_meta.json"

        local_size = runner.stat().st_size

        remote_exists = _run_cmd(["gcloud", "storage", "ls", canonical_uri]).returncode == 0
        remote_size = None
        if remote_exists:
            details = _run_cmd(["gcloud", "storage", "ls", "-L", canonical_uri], capture=True)
            if details.returncode == 0:
                for line in details.stdout.splitlines():
                    if "Content-Length:" in line:
                        value = line.split(":", 1)[1].strip().replace(",", "")
                        if value.isdigit():
                            remote_size = int(value)
                        break

        if (not force) and remote_exists and remote_size is not None and remote_size == local_size:
            print(f"Runner appears unchanged (size={local_size}); skipping upload. Use BMT_FORCE=1 to override.")
            return 0

        if remote_exists:
            cp_prev = _run_cmd(["gcloud", "storage", "cp", canonical_uri, previous_uri, "--quiet"])
            if cp_prev.returncode != 0:
                return cp_prev.returncode
            print(f"Rotated previous runner to {previous_uri}")

        cp_new = _run_cmd(["gcloud", "storage", "cp", str(runner), canonical_uri, "--quiet"])
        if cp_new.returncode != 0:
            return cp_new.returncode

        meta = {
            "uploaded_at_utc": Instant.now().format_iso(unit="second"),
            "source": source,
            "source_ref": source_ref,
            "size_bytes": local_size,
            "bucket_path": canonical_uri,
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            json.dump(meta, tmp, indent=2)
            _ = tmp.write("\n")
            tmp_path = Path(tmp.name)

        try:
            cp_meta = _run_cmd(["gcloud", "storage", "cp", str(tmp_path), meta_uri, "--quiet"])
            if cp_meta.returncode != 0:
                return cp_meta.returncode
        finally:
            tmp_path.unlink(missing_ok=True)

        print(f"Uploaded runner to {canonical_uri}")
        return 0


if __name__ == "__main__":
    bucket = bucket_from_env()
    runner_path = (
        os.environ.get("BMT_RUNNER_PATH") or ""
    ).strip() or "repo/staging/runners/sk_gcc_release/kardome_runner"
    runner_uri = (os.environ.get("BMT_RUNNER_URI") or "").strip() or "sk/runners/sk_gcc_release/kardome_runner"
    source = (os.environ.get("BMT_SOURCE") or "").strip() or "sandbox_manual"
    source_ref = (os.environ.get("SOURCE_REF") or "").strip()
    force = truthy(os.environ.get("BMT_FORCE"))
    raise SystemExit(
        BucketUploadRunner().run(
            bucket=bucket,
            runner_path=runner_path,
            runner_uri=runner_uri,
            source=source,
            source_ref=source_ref,
            force=force,
        )
    )

#!/usr/bin/env python3
"""Sync local deploy/runtime seed content into runtime namespace."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from whenever import Instant

from tools.repo.paths import DEFAULT_STAGE_ROOT
from tools.shared.bucket_env import bucket_from_env, runtime_bucket_root_uri, truthy
from tools.shared.bucket_sync import download_manifest, is_inputs_data_path, local_digest, matches
from tools.shared.layout_patterns import FORBIDDEN_RUNTIME_SEED

RUNTIME_SEED_MANIFEST = "_meta/runtime_seed_manifest.json"


def _local_digest(src: Path, allow_generated_artifacts: bool) -> tuple[str, int]:
    """Same digest as bucket_verify_runtime_seed_sync for idempotent skip check."""
    return local_digest(src, allow_generated_artifacts, FORBIDDEN_RUNTIME_SEED)


def _iter_source_files(src: Path, allow_generated_artifacts: bool) -> list[Path]:
    files: list[Path] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        # Same explicit guard as local_digest(): skip data files under projects/*/inputs/.
        if is_inputs_data_path(rel):
            continue
        if not allow_generated_artifacts and matches(FORBIDDEN_RUNTIME_SEED, rel):
            continue
        files.append(path)
    return files


def _local_manifest(src: Path, allow_generated_artifacts: bool) -> dict[str, object]:
    files: list[tuple[str, str, int]] = []
    for path in _iter_source_files(src, allow_generated_artifacts):
        rel = path.relative_to(src).as_posix()
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        files.append((rel, h.hexdigest(), path.stat().st_size))

    digest_input = "\n".join(f"{rel}|{sha}|{size}" for rel, sha, size in files).encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()
    return {
        "schema_version": 1,
        "synced_at": Instant.now().format_iso(unit="second"),
        "source_dir": str(src),
        "source_dir_name": src.name,
        "source_file_count": len(files),
        "source_digest_sha256": digest,
        "source_files": [{"path": rel, "sha256": sha, "size": size} for rel, sha, size in files],
        "allow_generated_artifacts": allow_generated_artifacts,
    }


def _upload_manifest(dest_root: str, manifest: dict[str, object]) -> int:
    with tempfile.TemporaryDirectory(prefix="runtime_seed_manifest_") as tmp_dir:
        path = Path(tmp_dir) / "runtime_seed_manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        uri = f"{dest_root}/{RUNTIME_SEED_MANIFEST}"
        print(f"Uploading runtime seed manifest -> {uri}")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(path), uri, "--quiet"],
            check=False,
        )
        return proc.returncode


class BucketSyncRuntimeSeed:
    """Sync local deploy/runtime seed content into runtime namespace."""

    def run(
        self,
        *,
        bucket: str,
        src_dir: Path | str = DEFAULT_STAGE_ROOT,
        delete: bool = False,
        allow_generated_artifacts: bool = False,
        force: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        src = Path(src_dir)
        if not src.is_dir():
            print(f"::error::Missing source directory: {src}", file=sys.stderr)
            return 1

        dest = runtime_bucket_root_uri(bucket)
        manifest_uri = f"{dest}/{RUNTIME_SEED_MANIFEST}"

        if not force:
            manifest = download_manifest(manifest_uri)
            if manifest and isinstance(manifest.get("source_digest_sha256"), str):
                local_d, local_count = _local_digest(src, allow_generated_artifacts)
                remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
                remote_count = int(manifest.get("source_file_count", -1))
                if local_d == remote_digest and local_count == remote_count:
                    print("Runtime seed already in sync with bucket; skipping. Use BMT_FORCE=1 to re-sync.")
                    return 0

        cmd = ["gcloud", "storage", "rsync", "--recursive"]
        if delete:
            cmd.append("--delete-unmatched-destination-objects")
        if not allow_generated_artifacts:
            for pattern in FORBIDDEN_RUNTIME_SEED:
                cmd.extend(["--exclude", pattern])
        cmd.extend([str(src), dest])

        print(f"Syncing runtime seed {src}/ -> {dest}/")
        if not allow_generated_artifacts:
            print("Excluding generated runtime artifacts by default.")
        rc = subprocess.run(cmd, check=False).returncode
        if rc != 0:
            return rc

        manifest = _local_manifest(src, allow_generated_artifacts)
        manifest["bucket"] = bucket
        return _upload_manifest(dest, manifest)


if __name__ == "__main__":
    bucket = bucket_from_env()
    src_dir = (os.environ.get("BMT_SRC_DIR") or "").strip() or DEFAULT_STAGE_ROOT
    delete = truthy(os.environ.get("BMT_DELETE"))
    allow_generated_artifacts = truthy(os.environ.get("BMT_ALLOW_GENERATED_ARTIFACTS"))
    force = truthy(os.environ.get("BMT_FORCE"))
    raise SystemExit(
        BucketSyncRuntimeSeed().run(
            bucket=bucket,
            src_dir=src_dir,
            delete=delete,
            allow_generated_artifacts=allow_generated_artifacts,
            force=force,
        )
    )

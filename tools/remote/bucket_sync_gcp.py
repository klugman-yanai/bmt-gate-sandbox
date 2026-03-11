#!/usr/bin/env python3
"""Sync local gcp/code mirror into bucket code namespace."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from tools.repo.paths import DEFAULT_CONFIG_ROOT
from tools.shared.bucket_env import bucket_from_env, code_bucket_root_uri, truthy
from tools.shared.bucket_sync import download_manifest, local_digest, matches
from tools.shared.layout_patterns import DEFAULT_CODE_EXCLUDES


def _iter_source_files(src: Path, include_runtime_artifacts: bool) -> list[Path]:
    files: list[Path] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if not include_runtime_artifacts and matches(DEFAULT_CODE_EXCLUDES, rel):
            continue
        files.append(path)
    return files


def _git_commit_sha() -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    sha = (proc.stdout or "").strip()
    return sha or None


def _local_manifest(src: Path, include_runtime_artifacts: bool) -> dict[str, object]:
    files: list[tuple[str, str, int]] = []
    for path in _iter_source_files(src, include_runtime_artifacts):
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
        "synced_at": datetime.now(UTC).isoformat(),
        "source_dir": str(src),
        "source_dir_name": src.name,
        "source_file_count": len(files),
        "source_digest_sha256": digest,
        "source_files": [{"path": rel, "sha256": sha, "size": size} for rel, sha, size in files],
        "git_commit_sha": _git_commit_sha(),
    }


def _upload_manifest(dest_root: str, manifest: dict[str, object]) -> int:
    with tempfile.TemporaryDirectory(prefix="remote_manifest_") as tmp_dir:
        path = Path(tmp_dir) / "remote_manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        uri = f"{dest_root}/_meta/remote_manifest.json"
        print(f"Uploading sync manifest -> {uri}")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(path), uri, "--quiet"],
            check=False,
        )
        return proc.returncode


class BucketSyncGcp:
    """Sync local gcp/code mirror into bucket code namespace."""

    def run(
        self,
        *,
        bucket: str,
        src_dir: str = DEFAULT_CONFIG_ROOT,
        delete: bool = False,
        include_runtime_artifacts: bool = False,
        force: bool = False,
    ) -> int:
        if not bucket:
            print("::error::Set GCS_BUCKET (or pass --bucket)", file=sys.stderr)
            return 1

        src = Path(src_dir)
        if not src.is_dir():
            print(f"::error::Missing source directory: {src}", file=sys.stderr)
            return 1

        dest = code_bucket_root_uri(bucket)
        manifest_uri = f"{dest}/_meta/remote_manifest.json"

        if not force:
            manifest = download_manifest(manifest_uri)
            if manifest and isinstance(manifest.get("source_digest_sha256"), str):
                local_d, local_count = local_digest(src, include_runtime_artifacts, DEFAULT_CODE_EXCLUDES)
                remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
                remote_count = int(manifest.get("source_file_count", -1))
                if local_d == remote_digest and local_count == remote_count:
                    print("Code already in sync with bucket; skipping. Use BMT_FORCE=1 to re-sync.")
                    return 0

        cmd = ["gcloud", "storage", "rsync", "--recursive"]
        if delete:
            cmd.append("--delete-unmatched-destination-objects")
        if not include_runtime_artifacts:
            for pattern in DEFAULT_CODE_EXCLUDES:
                cmd.extend(["--exclude", pattern])
        cmd.extend([str(src), dest])

        print(f"Syncing {src}/ -> {dest}/")
        if not include_runtime_artifacts:
            print("Excluding runtime/cache paths by default (use BMT_INCLUDE_RUNTIME_ARTIFACTS=1 to override).")
        rc = subprocess.run(cmd, check=False).returncode
        if rc != 0:
            return rc

        manifest = _local_manifest(src, include_runtime_artifacts)
        manifest["bucket"] = bucket
        manifest["code_prefix"] = "code"
        manifest["include_runtime_artifacts"] = include_runtime_artifacts
        if not include_runtime_artifacts:
            manifest["excluded_patterns"] = list(DEFAULT_CODE_EXCLUDES)
        return _upload_manifest(dest, manifest)


if __name__ == "__main__":
    import os

    bucket = bucket_from_env()
    src_dir = (os.environ.get("BMT_SRC_DIR") or "").strip() or DEFAULT_CONFIG_ROOT
    delete = truthy(os.environ.get("BMT_DELETE"))
    include_runtime_artifacts = truthy(os.environ.get("BMT_INCLUDE_RUNTIME_ARTIFACTS"))
    force = truthy(os.environ.get("BMT_FORCE"))
    raise SystemExit(
        BucketSyncGcp().run(
            bucket=bucket,
            src_dir=src_dir,
            delete=delete,
            include_runtime_artifacts=include_runtime_artifacts,
            force=force,
        )
    )

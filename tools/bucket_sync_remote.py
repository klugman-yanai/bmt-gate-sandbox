#!/usr/bin/env python3
"""Sync local deploy/code mirror into bucket code namespace."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from repo_paths import DEFAULT_CONFIG_ROOT
from shared_bucket_env import bucket_option, code_bucket_root_uri

# Exclude Python/uv cache, venvs, and build bloat. Use both path-anchored and substring
# patterns so __pycache__ etc. are excluded regardless of how gcloud applies the regex.
DEFAULT_CODE_EXCLUDES = (
    # Python bytecode and cache
    r"(^|/)__pycache__(/|$)",
    r"__pycache__",
    r"\.pyc$",
    r"\.pyo$",
    # Virtual environments and uv project cache
    r"(^|/)\.venv(/|$)",
    r"(^|/)venv(/|$)",
    r"(^|/)\.uv(/|$)",
    # Tool caches
    r"(^|/)\.mypy_cache(/|$)",
    r"(^|/)\.pytest_cache(/|$)",
    r"(^|/)\.ruff_cache(/|$)",
    r"(^|/)\.tox(/|$)",
    # Build/packaging
    r"(^|/)\.eggs(/|$)",
    r"(^|/)[^/]+\.egg-info(/|$)",
    r"\.egg$",
    # Runtime/BMT artifacts
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/inputs(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)sk/results(/|$)",
)

UV_ARTIFACT_REL = "_tools/uv/linux-x86_64/uv"
UV_CHECKSUM_REL = "_tools/uv/linux-x86_64/uv.sha256"


def _matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(pattern, rel) for pattern in patterns)


def _iter_source_files(src: Path, include_runtime_artifacts: bool) -> list[Path]:
    files: list[Path] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if not include_runtime_artifacts and _matches(DEFAULT_CODE_EXCLUDES, rel):
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


def _local_digest(src: Path, include_runtime_artifacts: bool) -> tuple[str, int]:
    """Same digest as bucket_verify_remote_sync for idempotent skip check."""
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
    return digest, len(files)


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
        "synced_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_dir": str(src),
        "source_dir_name": src.name,
        "source_file_count": len(files),
        "source_digest_sha256": digest,
        "source_files": [{"path": rel, "sha256": sha, "size": size} for rel, sha, size in files],
        "git_commit_sha": _git_commit_sha(),
    }


def _download_manifest(uri: str) -> dict[str, object] | None:
    proc = subprocess.run(
        ["gcloud", "storage", "cat", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _upload_manifest(dest_root: str, manifest: dict[str, object]) -> int:
    with tempfile.TemporaryDirectory(prefix="remote_manifest_") as tmp_dir:
        path = Path(tmp_dir) / "remote_manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        uri = f"{dest_root}/_meta/remote_manifest.json"
        click.echo(f"Uploading sync manifest -> {uri}")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(path), uri, "--quiet"],
            check=False,
        )
        return proc.returncode


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_expected_sha(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        token = stripped.split()[0]
        if token:
            return token
    return ""


def _upload_pinned_uv_artifact(src: Path, dest_root: str) -> dict[str, str]:
    sha_file = src / UV_CHECKSUM_REL
    if not sha_file.is_file():
        raise RuntimeError(f"Missing pinned uv checksum file: {sha_file}")

    expected_sha = _read_expected_sha(sha_file)
    if not expected_sha:
        raise RuntimeError(f"Invalid uv checksum file (missing digest): {sha_file}")

    uv_path_raw = (os.environ.get("BMT_UV_TOOL_PATH") or "").strip()
    if uv_path_raw:
        uv_tool_path = Path(uv_path_raw)
    else:
        uv_on_path = shutil.which("uv")
        if not uv_on_path:
            raise RuntimeError("uv binary not found. Set BMT_UV_TOOL_PATH or install uv locally.")
        uv_tool_path = Path(uv_on_path)
    if not uv_tool_path.is_file():
        raise RuntimeError(f"Configured uv artifact path is not a file: {uv_tool_path}")

    actual_sha = _sha256_file(uv_tool_path)
    if actual_sha != expected_sha:
        raise RuntimeError(
            "Pinned uv checksum mismatch. "
            f"Expected {expected_sha} from {sha_file}, got {actual_sha} from {uv_tool_path}. "
            "Update deploy/code/_tools/uv/linux-x86_64/uv.sha256 only when intentionally pinning a new uv build."
        )

    artifact_uri = f"{dest_root}/{UV_ARTIFACT_REL}"
    click.echo(f"Uploading pinned uv artifact -> {artifact_uri}")
    proc = subprocess.run(
        ["gcloud", "storage", "cp", str(uv_tool_path), artifact_uri, "--quiet"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to upload pinned uv artifact to {artifact_uri}")

    return {
        "uv_artifact_uri": artifact_uri,
        "uv_artifact_sha256": actual_sha,
        "uv_artifact_source": str(uv_tool_path),
    }


def _upload_manifest(dest_root: str, manifest: dict[str, object]) -> int:
    with tempfile.TemporaryDirectory(prefix="remote_manifest_") as tmp_dir:
        path = Path(tmp_dir) / "remote_manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        uri = f"{dest_root}/_meta/remote_manifest.json"
        click.echo(f"Uploading sync manifest -> {uri}")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(path), uri, "--quiet"],
            check=False,
        )
        return proc.returncode


@click.command()
@bucket_option
@click.option("--src-dir", default=DEFAULT_CONFIG_ROOT, help="Source directory to sync (canonical code mirror)")
@click.option("--delete", is_flag=True, help="Delete unmatched destination objects")
@click.option(
    "--include-runtime-artifacts",
    is_flag=True,
    help="Include runtime-generated paths (triggers, inputs, outputs, results).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force sync even if bucket manifest matches local (default: skip when already in sync).",
)
def main(
    bucket: str,
    src_dir: str,
    delete: bool,
    include_runtime_artifacts: bool,
    force: bool,
) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    src = Path(src_dir)
    if not src.is_dir():
        click.echo(f"::error::Missing source directory: {src}", err=True)
        return 1

    dest = code_bucket_root_uri(bucket)
    manifest_uri = f"{dest}/_meta/remote_manifest.json"

    if not force:
        manifest = _download_manifest(manifest_uri)
        if manifest and isinstance(manifest.get("source_digest_sha256"), str):
            local_digest, local_count = _local_digest(src, include_runtime_artifacts)
            remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
            remote_count = int(manifest.get("source_file_count", -1))
            if local_digest == remote_digest and local_count == remote_count:
                skip = True
                if not include_runtime_artifacts:
                    local_uv_sha = (
                        _read_expected_sha(src / UV_CHECKSUM_REL) if (src / UV_CHECKSUM_REL).is_file() else ""
                    )
                    remote_uv = str(manifest.get("uv_artifact_sha256", "")).strip()
                    if remote_uv and local_uv_sha != remote_uv:
                        skip = False
                if skip:
                    click.echo("Code already in sync with bucket; skipping. Use --force to re-sync.")
                    return 0

    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    if not include_runtime_artifacts:
        for pattern in DEFAULT_CODE_EXCLUDES:
            cmd.extend(["--exclude", pattern])
    cmd.extend([str(src), dest])

    click.echo(f"Syncing {src}/ -> {dest}/")
    if not include_runtime_artifacts:
        click.echo("Excluding runtime/cache paths by default (use --include-runtime-artifacts to override).")
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        return rc

    try:
        uv_metadata = _upload_pinned_uv_artifact(src, dest)
    except RuntimeError as exc:
        click.echo(f"::error::{exc}", err=True)
        return 1

    manifest = _local_manifest(src, include_runtime_artifacts)
    manifest["bucket"] = bucket
    manifest["code_prefix"] = "code"
    manifest.update(uv_metadata)
    manifest["include_runtime_artifacts"] = include_runtime_artifacts
    if not include_runtime_artifacts:
        manifest["excluded_patterns"] = list(DEFAULT_CODE_EXCLUDES)
    return _upload_manifest(dest, manifest)


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

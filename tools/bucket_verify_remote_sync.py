#!/usr/bin/env python3
"""Verify local deploy/code matches the manifest uploaded to code/current/_meta/remote_manifest.json."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from bucket_sync_remote import CURRENT_PREFIX, UV_ARTIFACT_REL, UV_CHECKSUM_REL, UV_RELEASE_SPEC_REL, _iter_source_files
from repo_paths import DEFAULT_CONFIG_ROOT
from shared_bucket_env import bucket_option, code_bucket_root_uri
from uv_pin import read_pinned_binary_sha


def _local_digest(src: Path, include_runtime_artifacts: bool) -> tuple[str, int]:
    files: list[tuple[str, str, int]] = []
    for path in _iter_source_files(src, include_runtime_artifacts):
        rel = path.relative_to(src).as_posix()
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        files.append((rel, h.hexdigest(), path.stat().st_size))
    digest_input = "\n".join(f"{rel}|{sha}|{size}" for rel, sha, size in files).encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest(), len(files)


def _download_manifest(uri: str) -> dict[str, object]:
    proc = subprocess.run(
        ["gcloud", "storage", "cat", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to read manifest {uri}: {(proc.stderr or proc.stdout).strip()}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Manifest at {uri} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Manifest at {uri} is not a JSON object")
    return payload


def _download_text(uri: str) -> str:
    proc = subprocess.run(
        ["gcloud", "storage", "cat", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to read object {uri}: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def _gcs_exists(uri: str) -> bool:
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


@click.command()
@bucket_option
@click.option("--src-dir", default=DEFAULT_CONFIG_ROOT, help="Source directory to verify")
@click.option(
    "--include-runtime-artifacts",
    is_flag=True,
    help="Deprecated compatibility flag (allowlist already excludes runtime artifacts).",
)
def main(bucket: str, src_dir: str, include_runtime_artifacts: bool) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    src = Path(src_dir)
    if not src.is_dir():
        click.echo(f"::error::Missing source directory: {src}", err=True)
        return 1

    code_root = code_bucket_root_uri(bucket)
    current_root = f"{code_root}/{CURRENT_PREFIX}"
    manifest_uri = f"{current_root}/_meta/remote_manifest.json"
    local_digest, local_count = _local_digest(src, include_runtime_artifacts)
    manifest = _download_manifest(manifest_uri)

    remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
    remote_count = int(manifest.get("source_file_count", -1))
    if not remote_digest:
        click.echo(f"::error::Manifest missing source_digest_sha256: {manifest_uri}", err=True)
        return 1

    if local_digest != remote_digest or local_count != remote_count:
        click.echo(f"::error::deploy/code is not in sync with {manifest_uri}", err=True)
        click.echo(
            f"Local digest={local_digest} count={local_count}; manifest digest={remote_digest} count={remote_count}",
            err=True,
        )
        return 1

    local_uv_sha = read_pinned_binary_sha(src / UV_CHECKSUM_REL, filename="uv")

    uv_uri = f"{current_root}/{UV_ARTIFACT_REL}"
    uv_sha_uri = f"{current_root}/{UV_CHECKSUM_REL}"
    uv_release_uri = f"{current_root}/{UV_RELEASE_SPEC_REL}"
    for uri in (uv_uri, uv_sha_uri, uv_release_uri):
        if not _gcs_exists(uri):
            click.echo(f"::error::Missing required pinned uv object: {uri}", err=True)
            return 1

    # Reuse strict parser for remote checksum content.
    from uv_pin import parse_sha256_line

    remote_uv_sha = parse_sha256_line(_download_text(uv_sha_uri), require_filename="uv")
    if remote_uv_sha != local_uv_sha:
        click.echo(
            f"::error::Pinned uv checksum mismatch between local source and bucket ({local_uv_sha} != {remote_uv_sha})",
            err=True,
        )
        return 1

    manifest_uv_sha = str(manifest.get("uv_artifact_sha256", "")).strip()
    if manifest_uv_sha and manifest_uv_sha != local_uv_sha:
        click.echo(
            "::error::Manifest uv_artifact_sha256 does not match pinned checksum "
            f"({manifest_uv_sha} != {local_uv_sha})",
            err=True,
        )
        return 1

    click.echo(f"Verified code mirror sync against {manifest_uri}")
    click.echo(f"Digest: {local_digest}")
    click.echo(f"File count: {local_count}")
    click.echo(f"Pinned UV SHA-256: {local_uv_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

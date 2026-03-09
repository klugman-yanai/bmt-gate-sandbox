#!/usr/bin/env python3
"""Verify local deploy/runtime matches runtime seed manifest in bucket."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from repo_paths import DEFAULT_RUNTIME_ROOT
from shared_bucket_env import bucket_option, runtime_bucket_root_uri

FORBIDDEN_RUNTIME_SEED = (
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/results(/|$)",
    r"(^|/)sk/outputs(/|$)",
)

RUNTIME_SEED_MANIFEST = "_meta/runtime_seed_manifest.json"


def _matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(pattern, rel) for pattern in patterns)


def _local_digest(src: Path, allow_generated_artifacts: bool) -> tuple[str, int]:
    files: list[tuple[str, str, int]] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if not allow_generated_artifacts and _matches(FORBIDDEN_RUNTIME_SEED, rel):
            continue
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


@click.command()
@bucket_option
@click.option("--src-dir", default=DEFAULT_RUNTIME_ROOT, help="Runtime seed source directory to verify")
@click.option(
    "--allow-generated-artifacts",
    is_flag=True,
    help="Include generated runtime artifacts (triggers/results/outputs) in digest.",
)
def main(bucket: str, src_dir: str, allow_generated_artifacts: bool) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    src = Path(src_dir)
    if not src.is_dir():
        click.echo(f"::error::Missing source directory: {src}", err=True)
        return 1

    runtime_root = runtime_bucket_root_uri(bucket)
    manifest_uri = f"{runtime_root}/{RUNTIME_SEED_MANIFEST}"
    local_digest, local_count = _local_digest(src, allow_generated_artifacts)

    try:
        manifest = _download_manifest(manifest_uri)
    except RuntimeError as exc:
        click.echo(f"::error::{exc}", err=True)
        return 1

    remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
    remote_count = int(manifest.get("source_file_count", -1))
    if not remote_digest:
        click.echo(f"::error::Runtime seed manifest missing source_digest_sha256: {manifest_uri}", err=True)
        return 1

    if local_digest != remote_digest or local_count != remote_count:
        click.echo(f"::error::deploy/runtime is not in sync with {manifest_uri}", err=True)
        click.echo(
            f"Local digest={local_digest} count={local_count}; manifest digest={remote_digest} count={remote_count}",
            err=True,
        )
        return 1

    click.echo(f"Verified runtime seed sync against {manifest_uri}")
    click.echo(f"Digest: {local_digest}")
    click.echo(f"File count: {local_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

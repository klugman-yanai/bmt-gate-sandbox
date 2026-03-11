#!/usr/bin/env python3
"""Verify local gcp/code matches the manifest uploaded to code/_meta/remote_manifest.json."""

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
from repo_paths import DEFAULT_CONFIG_ROOT
from shared_bucket_env import bucket_option, code_bucket_root_uri

DEFAULT_CODE_EXCLUDES = (
    r"(^|/)__pycache__(/|$)",
    r"__pycache__",
    r"\.pyc$",
    r"\.pyo$",
    r"(^|/)\.venv(/|$)",
    r"(^|/)venv(/|$)",
    r"(^|/)\.uv(/|$)",
    r"(^|/)\.mypy_cache(/|$)",
    r"(^|/)\.pytest_cache(/|$)",
    r"(^|/)\.ruff_cache(/|$)",
    r"(^|/)\.tox(/|$)",
    r"(^|/)\.eggs(/|$)",
    r"(^|/)[^/]+\.egg-info(/|$)",
    r"\.egg$",
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/inputs(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)sk/results(/|$)",
)



def _matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(pattern, rel) for pattern in patterns)


def _local_digest(src: Path, include_runtime_artifacts: bool) -> tuple[str, int]:
    files: list[tuple[str, str, int]] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if not include_runtime_artifacts and _matches(DEFAULT_CODE_EXCLUDES, rel):
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
@click.option("--src-dir", default=DEFAULT_CONFIG_ROOT, help="Source directory to verify")
@click.option(
    "--include-runtime-artifacts",
    is_flag=True,
    help="Include runtime-generated paths (triggers, inputs, outputs, results).",
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
    manifest_uri = f"{code_root}/_meta/remote_manifest.json"
    local_digest, local_count = _local_digest(src, include_runtime_artifacts)
    manifest = _download_manifest(manifest_uri)

    remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
    remote_count = int(manifest.get("source_file_count", -1))
    if not remote_digest:
        click.echo(f"::error::Manifest missing source_digest_sha256: {manifest_uri}", err=True)
        return 1

    if local_digest != remote_digest or local_count != remote_count:
        click.echo(f"::error::gcp/code is not in sync with {manifest_uri}", err=True)
        click.echo(
            f"Local digest={local_digest} count={local_count}; manifest digest={remote_digest} count={remote_count}",
            err=True,
        )
        return 1

    click.echo(f"Verified code mirror sync against {manifest_uri}")
    click.echo(f"Digest: {local_digest}")
    click.echo(f"File count: {local_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

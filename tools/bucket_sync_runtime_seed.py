#!/usr/bin/env python3
"""Sync local deploy/runtime seed content into runtime namespace."""

from __future__ import annotations

import hashlib
import json
import re
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
from repo_paths import DEFAULT_RUNTIME_ROOT
from shared_bucket_env import bucket_option, runtime_bucket_root_uri

FORBIDDEN_RUNTIME_SEED = (
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
    r"(^|/)sk/results(/|$)",
    r"(^|/)sk/outputs(/|$)",
)

RUNTIME_SEED_MANIFEST = "_meta/runtime_seed_manifest.json"


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


def _iter_source_files(src: Path, allow_generated_artifacts: bool) -> list[Path]:
    files: list[Path] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if not allow_generated_artifacts and any(re.search(pattern, rel) for pattern in FORBIDDEN_RUNTIME_SEED):
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
        "synced_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_dir": str(src),
        "source_dir_name": src.name,
        "source_file_count": len(files),
        "source_digest_sha256": digest,
        "source_files": [{"path": rel, "sha256": sha, "size": size} for rel, sha, size in files],
        "allow_generated_artifacts": allow_generated_artifacts,
    }


def _local_digest(src: Path, allow_generated_artifacts: bool) -> tuple[str, int]:
    """Same digest as bucket_verify_runtime_seed_sync for idempotent skip check."""
    m = _local_manifest(src, allow_generated_artifacts)
    return str(m["source_digest_sha256"]), int(m["source_file_count"])


def _upload_manifest(dest_root: str, manifest: dict[str, object]) -> int:
    with tempfile.TemporaryDirectory(prefix="runtime_seed_manifest_") as tmp_dir:
        path = Path(tmp_dir) / "runtime_seed_manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        uri = f"{dest_root}/{RUNTIME_SEED_MANIFEST}"
        click.echo(f"Uploading runtime seed manifest -> {uri}")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(path), uri, "--quiet"],
            check=False,
        )
        return proc.returncode


@click.command()
@bucket_option
@click.option("--src-dir", default=DEFAULT_RUNTIME_ROOT, help="Runtime seed source directory")
@click.option("--delete", is_flag=True, help="Delete unmatched destination objects")
@click.option(
    "--allow-generated-artifacts",
    is_flag=True,
    help="Allow syncing generated runtime artifacts (triggers/results/outputs).",
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
    allow_generated_artifacts: bool,
    force: bool,
) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    src = Path(src_dir)
    if not src.is_dir():
        click.echo(f"::error::Missing source directory: {src}", err=True)
        return 1

    dest = runtime_bucket_root_uri(bucket)
    manifest_uri = f"{dest}/{RUNTIME_SEED_MANIFEST}"

    if not force:
        manifest = _download_manifest(manifest_uri)
        if manifest and isinstance(manifest.get("source_digest_sha256"), str):
            local_digest, local_count = _local_digest(src, allow_generated_artifacts)
            remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
            remote_count = int(manifest.get("source_file_count", -1))
            if local_digest == remote_digest and local_count == remote_count:
                click.echo("Runtime seed already in sync with bucket; skipping. Use --force to re-sync.")
                return 0

    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    if not allow_generated_artifacts:
        for pattern in FORBIDDEN_RUNTIME_SEED:
            cmd.extend(["--exclude", pattern])
    cmd.extend([str(src), dest])

    click.echo(f"Syncing runtime seed {src}/ -> {dest}/")
    if not allow_generated_artifacts:
        click.echo("Excluding generated runtime artifacts by default.")
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        return rc

    manifest = _local_manifest(src, allow_generated_artifacts)
    manifest["bucket"] = bucket
    manifest["runtime_prefix"] = "runtime"
    return _upload_manifest(dest, manifest)


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

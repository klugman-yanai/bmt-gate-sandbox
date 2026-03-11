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
from uv_pin import fetch_pinned_uv_binary, read_pinned_binary_sha, read_release_spec

ALLOWED_TOP_FILES = {
    ".python-version",
    "bmt_projects.json",
    "pyproject.toml",
    "root_orchestrator.py",
    "uv.lock",
    "vm_watcher.py",
}

ALLOWED_STATIC_DIRS = {
    "bootstrap",
    "config",
    "lib",
}

# Exclude generated/cached/runtime paths even when they appear under otherwise-allowed roots.
FORBIDDEN_PATH_PATTERNS = (
    r"(^|/)__pycache__(/|$)",
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
    r"(^|/)bootstrap/out(/|$)",
    r"(^|/)_meta(/|$)",
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/inputs(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)sk/results(/|$)",
)

UV_ARTIFACT_REL = "_tools/uv/linux-x86_64/uv"
UV_CHECKSUM_REL = "_tools/uv/linux-x86_64/uv.sha256"
UV_RELEASE_SPEC_REL = "_tools/uv/linux-x86_64/uv.release.json"
RELEASES_PREFIX = "releases"
CURRENT_PREFIX = "current"

REQUIRED_RELEASE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "bootstrap/startup_example.sh",
    "bootstrap/startup_wrapper.sh",
    "bootstrap/ensure_uv.sh",
    "vm_watcher.py",
    "root_orchestrator.py",
    UV_CHECKSUM_REL,
    UV_RELEASE_SPEC_REL,
    UV_ARTIFACT_REL,
)


def _matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(pattern, rel) for pattern in patterns)


def _dynamic_project_dirs(src: Path) -> set[str]:
    project_dirs: set[str] = set()
    project_file = src / "bmt_projects.json"
    if project_file.is_file():
        try:
            payload = json.loads(project_file.read_text(encoding="utf-8"))
            projects = payload.get("projects") if isinstance(payload, dict) else None
            if isinstance(projects, dict):
                for key in projects:
                    name = str(key).strip()
                    if name and not name.startswith("."):
                        project_dirs.add(name)
        except (OSError, json.JSONDecodeError):
            pass

    for entry in sorted(src.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if (entry / "bmt_manager.py").is_file():
            project_dirs.add(entry.name)
    return project_dirs


def _is_allowlisted(rel: str, *, project_dirs: set[str]) -> bool:
    if rel in ALLOWED_TOP_FILES:
        return True
    if rel in {UV_CHECKSUM_REL, UV_RELEASE_SPEC_REL}:
        return True

    parts = rel.split("/", 1)
    top = parts[0]
    if top in ALLOWED_STATIC_DIRS:
        return True
    if top in project_dirs:
        return True
    return False


def _iter_source_files(src: Path, include_runtime_artifacts: bool) -> list[Path]:
    del include_runtime_artifacts  # kept for CLI compatibility; allowlist is authoritative.
    files: list[Path] = []
    project_dirs = _dynamic_project_dirs(src)
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if _matches(FORBIDDEN_PATH_PATTERNS, rel):
            continue
        if not _is_allowlisted(rel, project_dirs=project_dirs):
            continue
        files.append(path)
    return files


def _stage_allowlist_source(src: Path, files: list[Path]) -> Path:
    staged = Path(tempfile.mkdtemp(prefix="code_sync_stage_"))
    for path in files:
        rel_path = path.relative_to(src)
        dest = staged / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return staged


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


def _digest_for_files(src: Path, files: list[Path]) -> tuple[str, int, list[tuple[str, str, int]]]:
    rows: list[tuple[str, str, int]] = []
    for path in files:
        rel = path.relative_to(src).as_posix()
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        rows.append((rel, h.hexdigest(), path.stat().st_size))
    digest_input = "\n".join(f"{rel}|{sha}|{size}" for rel, sha, size in rows).encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()
    return digest, len(rows), rows


def _local_digest(src: Path, include_runtime_artifacts: bool) -> tuple[str, int]:
    files = _iter_source_files(src, include_runtime_artifacts)
    digest, count, _ = _digest_for_files(src, files)
    return digest, count


def _local_manifest(src: Path, include_runtime_artifacts: bool) -> dict[str, object]:
    files = _iter_source_files(src, include_runtime_artifacts)
    digest, count, rows = _digest_for_files(src, files)
    return {
        "schema_version": 2,
        "synced_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_dir": str(src),
        "source_dir_name": src.name,
        "source_file_count": count,
        "source_digest_sha256": digest,
        "source_files": [{"path": rel, "sha256": sha, "size": size} for rel, sha, size in rows],
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
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


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


def _sync_tree(src: str, dest: str, *, delete: bool) -> int:
    cmd = ["gcloud", "storage", "rsync", "--recursive"]
    if delete:
        cmd.append("--delete-unmatched-destination-objects")
    cmd.extend([src, dest])
    return subprocess.run(cmd, check=False).returncode


def _gcs_exists(uri: str) -> bool:
    proc = subprocess.run(
        ["gcloud", "storage", "ls", uri],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def _verify_release_contract(code_root: str) -> None:
    missing = [f"{code_root}/{rel}" for rel in REQUIRED_RELEASE_FILES if not _gcs_exists(f"{code_root}/{rel}")]
    if missing:
        raise RuntimeError(
            "Release code root missing required objects:\n"
            + "\n".join(f"  - {uri}" for uri in missing)
        )


def _derive_release_id() -> str:
    env_id = (os.environ.get("BMT_CODE_RELEASE_ID") or "").strip()
    if env_id:
        return re.sub(r"[^a-zA-Z0-9._-]", "-", env_id)[:128]
    sha = _git_commit_sha()
    if sha:
        return sha[:12]
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _upload_pinned_uv_artifact(src: Path, dest_root: str) -> dict[str, str]:
    sha_file = src / UV_CHECKSUM_REL
    release_file = src / UV_RELEASE_SPEC_REL
    expected_sha = read_pinned_binary_sha(sha_file, filename="uv")
    spec = read_release_spec(release_file)

    if spec.binary_sha256 != expected_sha:
        raise RuntimeError(
            "Pinned uv checksum mismatch between uv.sha256 and uv.release.json: "
            f"{expected_sha} != {spec.binary_sha256}"
        )

    with tempfile.TemporaryDirectory(prefix="uv_pinned_") as tmp_dir:
        uv_bin = fetch_pinned_uv_binary(spec, Path(tmp_dir))
        artifact_uri = f"{dest_root}/{UV_ARTIFACT_REL}"
        click.echo(f"Uploading pinned uv artifact -> {artifact_uri}")
        proc = subprocess.run(
            ["gcloud", "storage", "cp", str(uv_bin), artifact_uri, "--quiet"],
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to upload pinned uv artifact to {artifact_uri}")

    return {
        "uv_artifact_uri": artifact_uri,
        "uv_artifact_sha256": expected_sha,
        "uv_version": spec.version,
        "uv_artifact_url": spec.artifact_url,
        "uv_artifact_tar_sha256": spec.artifact_sha256,
        "uv_compat_target": f"ubuntu-22.04 glibc<={spec.glibc_max[0]}.{spec.glibc_max[1]}",
    }


@click.command()
@bucket_option
@click.option("--src-dir", default=DEFAULT_CONFIG_ROOT, help="Source directory to sync (canonical code mirror)")
@click.option("--delete", is_flag=True, help="Delete unmatched destination objects during current promotion")
@click.option(
    "--include-runtime-artifacts",
    is_flag=True,
    help="Deprecated compatibility flag (allowlist already excludes runtime artifacts).",
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

    code_root = code_bucket_root_uri(bucket)
    current_root = f"{code_root}/{CURRENT_PREFIX}"
    current_manifest_uri = f"{current_root}/_meta/remote_manifest.json"

    if not force:
        manifest = _download_manifest(current_manifest_uri)
        if manifest and isinstance(manifest.get("source_digest_sha256"), str):
            local_digest, local_count = _local_digest(src, include_runtime_artifacts)
            remote_digest = str(manifest.get("source_digest_sha256", "")).strip()
            remote_count = int(manifest.get("source_file_count", -1))
            if local_digest == remote_digest and local_count == remote_count:
                local_uv_sha = read_pinned_binary_sha(src / UV_CHECKSUM_REL, filename="uv")
                remote_uv = str(manifest.get("uv_artifact_sha256", "")).strip()
                if remote_uv and local_uv_sha == remote_uv:
                    click.echo("Code already in sync with bucket current channel; skipping. Use --force to re-sync.")
                    return 0

    allowlisted_files = _iter_source_files(src, include_runtime_artifacts)
    if not allowlisted_files:
        click.echo("::error::No allowlisted files found under source directory.", err=True)
        return 1

    stage_dir = _stage_allowlist_source(src, allowlisted_files)
    release_id = _derive_release_id()
    release_root = f"{code_root}/{RELEASES_PREFIX}/{release_id}"

    try:
        click.echo(f"Staging allowlisted source ({len(allowlisted_files)} files) -> {stage_dir}")
        click.echo(f"Syncing staged source -> release root {release_root}/")
        rc = _sync_tree(str(stage_dir), release_root, delete=True)
        if rc != 0:
            return rc

        uv_metadata = _upload_pinned_uv_artifact(src, release_root)

        release_manifest = _local_manifest(src, include_runtime_artifacts)
        release_manifest["bucket"] = bucket
        release_manifest["code_prefix"] = "code"
        release_manifest["release_id"] = release_id
        release_manifest["active_code_root"] = current_root
        release_manifest.update(uv_metadata)
        release_manifest["include_runtime_artifacts"] = include_runtime_artifacts

        manifest_rc = _upload_manifest(release_root, release_manifest)
        if manifest_rc != 0:
            return manifest_rc

        _verify_release_contract(release_root)

        click.echo(f"Promoting release -> current channel: {release_root}/ -> {current_root}/")
        promote_rc = _sync_tree(release_root, current_root, delete=delete)
        if promote_rc != 0:
            return promote_rc

        current_manifest = dict(release_manifest)
        current_manifest["promoted_from_release"] = release_id
        current_manifest["synced_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        current_manifest_rc = _upload_manifest(current_root, current_manifest)
        if current_manifest_rc != 0:
            return current_manifest_rc

        with tempfile.TemporaryDirectory(prefix="current_release_ptr_") as tmp_dir:
            pointer = Path(tmp_dir) / "current_release.json"
            pointer.write_text(
                json.dumps(
                    {
                        "release_id": release_id,
                        "current_code_root": current_root,
                        "release_code_root": release_root,
                        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            ptr_uri = f"{code_root}/_meta/current_release.json"
            subprocess.run(["gcloud", "storage", "cp", str(pointer), ptr_uri, "--quiet"], check=False)

        click.echo(f"Release published: {release_root}")
        click.echo(f"Current channel updated: {current_root}")
        return 0
    except RuntimeError as exc:
        click.echo(f"::error::{exc}", err=True)
        return 1
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

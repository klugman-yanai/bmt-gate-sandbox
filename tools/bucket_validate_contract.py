#!/usr/bin/env python3
"""Validate code/runtime bucket contract for manual sync deployments."""

from __future__ import annotations

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
from bucket_sync_remote import CURRENT_PREFIX, UV_CHECKSUM_REL, UV_RELEASE_SPEC_REL
from shared_bucket_env import bucket_option, code_bucket_root_uri, runtime_bucket_root_uri
from uv_pin import parse_sha256_line

REQUIRED_CODE = [
    "root_orchestrator.py",
    "bmt_projects.json",
    "pyproject.toml",
    "sk/bmt_manager.py",
    "sk/config/bmt_jobs.json",
    "sk/config/input_template.json",
    "uv.lock",
    "_tools/uv/linux-x86_64/uv",
    UV_CHECKSUM_REL,
    UV_RELEASE_SPEC_REL,
    "bootstrap/ensure_uv.sh",
    "bootstrap/startup_wrapper.sh",
    "bootstrap/startup_example.sh",
    "_meta/remote_manifest.json",
]

REQUIRED_RUNTIME = [
    "sk/results/false_rejects/current.json",
]

FORBIDDEN_CODE_PATTERNS = (
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
)


def _matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(pattern, rel) for pattern in patterns)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def exists(uri: str) -> bool:
    return (
        subprocess.run(
            ["gcloud", "storage", "ls", uri],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def has_snapshot_leaf(runtime_root: str, results_prefix: str, leaf_name: str) -> bool:
    uri = f"{runtime_root}/{results_prefix.rstrip('/')}/snapshots/*/{leaf_name}"
    proc = _run(["gcloud", "storage", "ls", uri])
    return proc.returncode == 0 and bool((proc.stdout or "").strip())


def _download_text(uri: str) -> str:
    proc = _run(["gcloud", "storage", "cat", uri])
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to read {uri}: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def _list_recursive(prefix: str) -> list[str]:
    proc = _run(["gcloud", "storage", "ls", "--recursive", prefix])
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def _forbidden_hits(code_root: str) -> list[str]:
    uris = _list_recursive(f"{code_root}/")
    rel_hits: list[str] = []
    prefix = f"{code_root}/"
    for uri in uris:
        if not uri.startswith(prefix):
            continue
        rel = uri[len(prefix) :]
        if _matches(FORBIDDEN_CODE_PATTERNS, rel):
            rel_hits.append(rel)
    return sorted(set(rel_hits))


def _resolve_active_code_root(bucket: str) -> tuple[str, str]:
    code_root = code_bucket_root_uri(bucket)
    current_root = f"{code_root}/{CURRENT_PREFIX}"
    if exists(f"{current_root}/bootstrap/startup_example.sh"):
        return current_root, "current"
    return code_root, "legacy"


@click.command()
@bucket_option
@click.option(
    "--require-runner",
    is_flag=True,
    help="Also require canonical runner binary object to exist in runtime namespace.",
)
def main(bucket: str, require_runner: bool) -> int:
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    active_code_root, mode = _resolve_active_code_root(bucket)
    runtime_root = runtime_bucket_root_uri(bucket)
    missing = False

    click.echo(f"Validating code root: {active_code_root} (mode={mode})")
    for rel in REQUIRED_CODE:
        uri = f"{active_code_root}/{rel}"
        if exists(uri):
            click.echo(f"FOUND {uri}")
        else:
            click.echo(f"::error::Missing required code object: {uri}", err=True)
            missing = True

    if mode == "current":
        pointer_uri = f"{code_bucket_root_uri(bucket)}/_meta/current_release.json"
        if exists(pointer_uri):
            click.echo(f"FOUND {pointer_uri}")
        else:
            click.echo(f"::warning::Missing release pointer object: {pointer_uri}", err=True)

    click.echo(f"Validating runtime root: {runtime_root}")
    for rel in REQUIRED_RUNTIME:
        uri = f"{runtime_root}/{rel}"
        if exists(uri):
            click.echo(f"FOUND {uri}")
        else:
            click.echo(f"::error::Missing required runtime object: {uri}", err=True)
            missing = True

    results_prefix = "sk/results/false_rejects"
    if has_snapshot_leaf(runtime_root, results_prefix, "latest.json"):
        click.echo(f"FOUND snapshot latest.json under {runtime_root}/{results_prefix}/snapshots/")
    else:
        click.echo(
            f"::error::Missing canonical snapshot latest.json under {runtime_root}/{results_prefix}/snapshots/",
            err=True,
        )
        missing = True

    if has_snapshot_leaf(runtime_root, results_prefix, "ci_verdict.json"):
        click.echo(f"FOUND snapshot ci_verdict.json under {runtime_root}/{results_prefix}/snapshots/")
    else:
        click.echo(
            f"::error::Missing canonical snapshot ci_verdict.json under {runtime_root}/{results_prefix}/snapshots/",
            err=True,
        )
        missing = True

    if require_runner:
        runner_uri = f"{runtime_root}/sk/runners/sk_gcc_release/kardome_runner"
        if exists(runner_uri):
            click.echo(f"FOUND {runner_uri}")
        else:
            click.echo(f"::error::Missing required object: {runner_uri}", err=True)
            missing = True

    uv_sha_uri = f"{active_code_root}/{UV_CHECKSUM_REL}"
    manifest_uri = f"{active_code_root}/_meta/remote_manifest.json"
    try:
        uv_sha = parse_sha256_line(_download_text(uv_sha_uri), require_filename="uv")
        manifest = json.loads(_download_text(manifest_uri))
        if not isinstance(manifest, dict):
            raise RuntimeError("manifest payload is not a JSON object")
        manifest_uv = str(manifest.get("uv_artifact_sha256", "")).strip().lower()
        if manifest_uv and manifest_uv != uv_sha:
            raise RuntimeError(
                f"manifest uv_artifact_sha256 mismatch ({manifest_uv} != {uv_sha})"
            )
        click.echo(f"Pinned uv sha verified: {uv_sha}")
    except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
        click.echo(f"::error::UV manifest consistency check failed: {exc}", err=True)
        missing = True

    forbidden = _forbidden_hits(active_code_root)
    if forbidden:
        click.echo("::error::Forbidden objects found under code root:", err=True)
        for rel in forbidden[:40]:
            click.echo(f"  - {rel}", err=True)
        if len(forbidden) > 40:
            click.echo(f"  ... and {len(forbidden) - 40} more", err=True)
        missing = True

    if missing:
        return 1

    click.echo("Bucket contract validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

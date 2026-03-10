#!/usr/bin/env python3
"""Pull bucket content into local deploy/ so deploy/ is a 1:1 mirror of the bucket (code + runtime).

Use this to sync local deploy/ with what is actually in GCS (e.g. after CI has uploaded
runner artifacts to runtime/<project>/runners/<preset>/). Excludes ephemeral runtime
paths (triggers/, results/, outputs/) so deploy/runtime stays valid per layout policy.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from repo_paths import DEFAULT_CONFIG_ROOT, DEFAULT_RUNTIME_ROOT
from shared_bucket_env import bucket_option, code_bucket_root_uri, runtime_bucket_root_uri

# Exclude ephemeral/generated paths so deploy/ stays valid per deploy_layout_policy.
# gcloud storage rsync --exclude uses glob-style patterns.
CODE_EXCLUDES = [
    ".venv",
    ".venv/**",
    "**/.venv/**",
    "venv",
    "venv/**",
    ".uv",
    ".uv/**",
    "__pycache__",
    "**/__pycache__/**",
    "*.pyc",
    "*.pyo",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "*.egg-info",
    "*.egg",
    "triggers",
    "triggers/**",
    "sk/inputs",
    "sk/inputs/**",
    "sk/outputs",
    "sk/outputs/**",
    "sk/results",
    "sk/results/**",
]
RUNTIME_EXCLUDES = [
    "triggers",
    "triggers/**",
    "**/results",
    "**/results/**",
    "**/outputs",
    "**/outputs/**",
    "**/inputs",
    "**/inputs/**",
    "_workflow",
    "_workflow/**",
]


def _run_rsync(
    source: str,
    dest: Path,
    excludes: list[str] | None = None,
    dry_run: bool = False,
) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["gcloud", "storage", "rsync", "--recursive", source, str(dest)]
    if excludes:
        for pattern in excludes:
            cmd.extend(["--exclude", pattern])
    if dry_run:
        cmd.append("--dry-run")
    click.echo(f"Rsync {source} -> {dest}/")
    return subprocess.run(cmd, check=False).returncode


@click.command()
@bucket_option
@click.option(
    "--code-dir",
    default=DEFAULT_CONFIG_ROOT,
    help="Local code mirror directory (default: deploy/code)",
)
@click.option(
    "--runtime-dir",
    default=DEFAULT_RUNTIME_ROOT,
    help="Local runtime mirror directory (default: deploy/runtime)",
)
@click.option("--dry-run", is_flag=True, help="Print what would be copied without writing")
def main(bucket: str, code_dir: str, runtime_dir: str, dry_run: bool) -> int:
    """Pull bucket code/ and runtime/ into local deploy/ for a 1:1 mirror."""
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    code_root = Path(code_dir)
    runtime_root = Path(runtime_dir)
    if not code_root.parent.exists():
        click.echo(f"::error::Parent of code dir must exist: {code_root.parent}", err=True)
        return 1
    if not runtime_root.parent.exists():
        click.echo(f"::error::Parent of runtime dir must exist: {runtime_root.parent}", err=True)
        return 1

    code_uri = code_bucket_root_uri(bucket)
    runtime_uri = runtime_bucket_root_uri(bucket)

    rc = _run_rsync(code_uri, code_root, excludes=CODE_EXCLUDES, dry_run=dry_run)
    if rc != 0:
        return rc
    rc = _run_rsync(runtime_uri, runtime_root, excludes=RUNTIME_EXCLUDES, dry_run=dry_run)
    if rc != 0:
        return rc

    click.echo("Pull complete. deploy/ is now in sync with bucket (excluding ephemeral runtime paths).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

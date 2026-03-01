#!/usr/bin/env python3
"""Remove Python/uv bloat objects from GCS code (and optionally runtime) namespace.

Lists objects under the chosen prefix(es), filters by the same bloat patterns used
in bucket_sync_remote.py, and deletes them. Default is --dry-run (no deletions).
Use --execute to perform deletions. Run from repo root with GCS_BUCKET set.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import click
from click_exit import run_click_command

_path = Path(__file__).resolve().parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))
from shared_bucket_env import (
    bucket_option,
    code_bucket_root_uri,
    runtime_bucket_root_uri,
)

# Bloat-only patterns (do not include triggers/sk paths; those are valid under runtime).
BLOAT_PATTERNS = (
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
)

# Under code namespace we also remove errant triggers/sk paths if present.
CODE_CLEAN_PATTERNS = BLOAT_PATTERNS + (
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/inputs(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)sk/results(/|$)",
)

BATCH_SIZE = 500  # URIs per gcloud storage rm call to avoid argv length limits


def _matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(p, rel) for p in patterns)


def _list_uris(prefix_uri: str) -> list[str]:
    """List all object URIs under prefix (recursive)."""
    proc = subprocess.run(
        ["gcloud", "storage", "ls", prefix_uri.rstrip("/") + "/", "--recursive"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "").strip()
    uris = [line.strip() for line in out.splitlines() if line.strip()]
    if proc.returncode != 0 and not uris:
        no_match = "One or more URLs matched no objects" in (proc.stderr or "")
        if not no_match:
            raise RuntimeError(f"gcloud storage ls failed: {proc.stderr or proc.stdout}")
    return uris


def _rel_path(uri: str, prefix_uri: str) -> str:
    """Object path relative to prefix (no gs://bucket/prefix/)."""
    base = prefix_uri.rstrip("/") + "/"
    if not uri.startswith(base):
        return uri
    return uri[len(base) :]


def _filter_bloat(uris: list[str], prefix_uri: str, patterns: tuple[str, ...]) -> list[str]:
    return [u for u in uris if _matches(patterns, _rel_path(u, prefix_uri))]


def _delete_uris(uris: list[str], dry_run: bool) -> None:
    if not uris:
        return
    if dry_run:
        for u in uris:
            click.echo(f"  [dry-run] would remove: {u}")
        return
    for i in range(0, len(uris), BATCH_SIZE):
        batch = uris[i : i + BATCH_SIZE]
        subprocess.run(
            ["gcloud", "storage", "rm", "--quiet", *batch],
            check=True,
        )


@click.command()
@bucket_option
@click.option(
    "--scope",
    type=click.Choice(["code", "runtime", "both"]),
    default="code",
    help="Namespace(s) to clean (code and/or runtime).",
)
@click.option(
    "--dry-run/--execute",
    "dry_run",
    default=True,
    help="Only list what would be removed (default). Use --execute to delete.",
)
def main(bucket: str, scope: str, dry_run: bool) -> int:
    """Remove Python/uv bloat from GCS code and/or runtime namespace."""
    if not bucket:
        click.echo("::error::Set GCS_BUCKET (or pass --bucket)", err=True)
        return 1

    to_clean: list[tuple[str, tuple[str, ...]]] = []
    if scope in ("code", "both"):
        to_clean.append((code_bucket_root_uri(bucket), CODE_CLEAN_PATTERNS))
    if scope in ("runtime", "both"):
        to_clean.append((runtime_bucket_root_uri(bucket), BLOAT_PATTERNS))

    total_removed = 0
    for prefix_uri, patterns in to_clean:
        label = "code" if "code" in prefix_uri else "runtime"
        click.echo(f"Listing {label} namespace: {prefix_uri}")
        uris = _list_uris(prefix_uri)
        bloat = _filter_bloat(uris, prefix_uri, patterns)
        if not bloat:
            click.echo(f"  No bloat objects under {prefix_uri}")
            continue
        click.echo(f"  Found {len(bloat)} bloat object(s) to remove.")
        _delete_uris(bloat, dry_run=dry_run)
        total_removed += len(bloat)

    if dry_run:
        if total_removed:
            click.echo(f"Would remove {total_removed} object(s). Run with --execute to perform deletions.")
        else:
            click.echo("No bloat objects found.")
    else:
        click.echo(f"Removed {total_removed} object(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

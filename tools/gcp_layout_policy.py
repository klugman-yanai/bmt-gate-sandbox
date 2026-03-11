#!/usr/bin/env python3
"""Validate canonical gcp/ layout as a 1:1 bucket mirror."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import click
from click_exit import run_click_command

ALLOWED_TOP_LEVEL = {
    "README.md",
    "code",
    "runtime",
}

REQUIRED_CODE_FILES = (
    "pyproject.toml",
    "root_orchestrator.py",
    "vm_watcher.py",
    "bootstrap/startup_wrapper.sh",
    "bootstrap/startup_example.sh",
    "config/github_repos.json",
    "lib/status_file.py",
    "sk/bmt_manager.py",
    "sk/config/bmt_jobs.json",
    "sk/config/input_template.json",
)

FORBIDDEN_CODE_PATTERNS = (
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

FORBIDDEN_RUNTIME_PATTERNS = (
    r"(^|/)triggers(/|$)",
    r"(^|/)sk/results(/|$)",
    r"(^|/)sk/outputs(/|$)",
    r"(^|/)inputs(/|$).*\.wav$",
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


def _matches(patterns: tuple[str, ...], rel: str) -> bool:
    return any(re.search(pattern, rel) for pattern in patterns)


@click.command()
def main() -> int:
    root = Path("gcp")
    code_root = root / "code"
    runtime_seed_root = root / "runtime"

    missing = False

    if not root.is_dir():
        click.echo("::error::Missing gcp/ directory", err=True)
        return 1

    for path in (code_root, runtime_seed_root):
        if not path.exists():
            click.echo(f"::error::Missing canonical path: {path}", err=True)
            missing = True

    for rel in REQUIRED_CODE_FILES:
        p = code_root / rel
        if not p.exists():
            click.echo(f"::error::Missing required code mirror object: {p}", err=True)
            missing = True

    # Only validate git-tracked paths under gcp/ so local .venv/cache dirs do not fail
    proc = subprocess.run(
        ["git", "ls-files", "--", "gcp/"],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path.cwd(),
    )
    tracked_under_gcp = set()
    if proc.returncode == 0 and proc.stdout:
        for raw in proc.stdout.splitlines():
            line = raw.strip()
            if not line or not line.startswith("gcp/"):
                continue
            tracked_under_gcp.add(line[4:])  # drop "gcp/" prefix

    code_prefix = "code/"
    forbidden_hits: list[str] = []
    for rel in sorted(tracked_under_gcp):
        if not rel.startswith(code_prefix):
            continue
        rel_in_code = rel[len(code_prefix) :]
        if _matches(FORBIDDEN_CODE_PATTERNS, rel_in_code):
            forbidden_hits.append(rel_in_code)

    if forbidden_hits:
        click.echo("::error::Forbidden runtime/generated paths found in gcp/code:", err=True)
        for rel in forbidden_hits[:30]:
            click.echo(f"  - {rel}", err=True)
        if len(forbidden_hits) > 30:
            click.echo(f"  ... and {len(forbidden_hits) - 30} more", err=True)
        missing = True

    runtime_prefix = "runtime/"
    forbidden_runtime_hits = []
    for rel in sorted(tracked_under_gcp):
        if not rel.startswith(runtime_prefix):
            continue
        rel_in_runtime = rel[len(runtime_prefix) :]
        if _matches(FORBIDDEN_RUNTIME_PATTERNS, rel_in_runtime):
            forbidden_runtime_hits.append(rel_in_runtime)

    if forbidden_runtime_hits:
        click.echo("::error::Forbidden generated/runtime paths found in gcp/runtime:", err=True)
        for rel in forbidden_runtime_hits[:30]:
            click.echo(f"  - {rel}", err=True)
        if len(forbidden_runtime_hits) > 30:
            click.echo(f"  ... and {len(forbidden_runtime_hits) - 30} more", err=True)
        missing = True

    unexpected_top_level = sorted(
        entry.name for entry in root.iterdir() if entry.name not in ALLOWED_TOP_LEVEL and not entry.name.startswith(".")
    )
    if unexpected_top_level:
        click.echo("::error::gcp/ must be a direct bucket mirror with only code/ and runtime/.", err=True)
        for name in unexpected_top_level:
            click.echo(f"  - unexpected: gcp/{name}", err=True)
        missing = True

    if missing:
        return 1

    click.echo("GCP layout policy check passed")
    click.echo(f"Code mirror root: {code_root}")
    click.echo(f"Runtime seed root: {runtime_seed_root}")
    click.echo(f"Top-level entries: {', '.join(sorted(ALLOWED_TOP_LEVEL))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

#!/usr/bin/env python3
"""Validate canonical deploy/ layout as a 1:1 bucket mirror."""

from __future__ import annotations

import re
from pathlib import Path

import click
from click_exit import run_click_command

ALLOWED_TOP_LEVEL = {
    "README.md",
    "code",
    "runtime",
}

REQUIRED_CODE_FILES = (
    "bmt_projects.json",
    "pyproject.toml",
    "root_orchestrator.py",
    "uv.lock",
    "vm_watcher.py",
    "_tools/uv/linux-x86_64/uv.sha256",
    "bootstrap/ensure_uv.sh",
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
    root = Path("deploy")
    code_root = root / "code"
    runtime_seed_root = root / "runtime"

    missing = False

    if not root.is_dir():
        click.echo("::error::Missing deploy/ directory", err=True)
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

    forbidden_hits: list[str] = []
    for p in sorted(x for x in code_root.rglob("*") if x.is_file()):
        rel = p.relative_to(code_root).as_posix()
        if _matches(FORBIDDEN_CODE_PATTERNS, rel):
            forbidden_hits.append(rel)

    if forbidden_hits:
        click.echo("::error::Forbidden runtime/generated paths found in deploy/code:", err=True)
        for rel in forbidden_hits[:30]:
            click.echo(f"  - {rel}", err=True)
        if len(forbidden_hits) > 30:
            click.echo(f"  ... and {len(forbidden_hits) - 30} more", err=True)
        missing = True

    forbidden_runtime_hits: list[str] = []
    for p in sorted(x for x in runtime_seed_root.rglob("*") if x.is_file()):
        rel = p.relative_to(runtime_seed_root).as_posix()
        if _matches(FORBIDDEN_RUNTIME_PATTERNS, rel):
            forbidden_runtime_hits.append(rel)

    if forbidden_runtime_hits:
        click.echo("::error::Forbidden generated/runtime paths found in deploy/runtime:", err=True)
        for rel in forbidden_runtime_hits[:30]:
            click.echo(f"  - {rel}", err=True)
        if len(forbidden_runtime_hits) > 30:
            click.echo(f"  ... and {len(forbidden_runtime_hits) - 30} more", err=True)
        missing = True

    unexpected_top_level = sorted(
        entry.name for entry in root.iterdir() if entry.name not in ALLOWED_TOP_LEVEL and not entry.name.startswith(".")
    )
    if unexpected_top_level:
        click.echo("::error::deploy/ must be a direct bucket mirror with only code/ and runtime/.", err=True)
        for name in unexpected_top_level:
            click.echo(f"  - unexpected: deploy/{name}", err=True)
        missing = True

    if missing:
        return 1

    click.echo("Deploy layout policy check passed")
    click.echo(f"Code mirror root: {code_root}")
    click.echo(f"Runtime seed root: {runtime_seed_root}")
    click.echo(f"Top-level entries: {', '.join(sorted(ALLOWED_TOP_LEVEL))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))

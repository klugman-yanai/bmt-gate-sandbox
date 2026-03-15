#!/usr/bin/env python3
"""Validate top-level repository layout policy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.repo.paths import DEFAULT_CONFIG_ROOT

ALLOWED_TRACKED_TOP_LEVEL = {
    ".actrc",
    ".cursorignore",
    ".env.example",
    ".gitattributes",
    ".github",
    ".gitignore",
    ".pre-commit-config.yaml",
    ".python-version",
    "CHANGELOG.md",
    "CLAUDE.md",
    "CMakePresets.json",
    "CMakeLists.txt",
    "Justfile",
    "README.md",
    "cache",
    "docs",
    "gcp",
    "infra",
    "pyproject.toml",
    "pyrightconfig.json",
    "ruff.toml",
    "schemas",
    "scripts",
    "tests",
    "tools",
    "uv.lock",
    ".canary-bmt-pr-test-20260305",
}

FORBIDDEN_TRACKED_PREFIXES = (
    "debug/",
    "resources/",
)

FORBIDDEN_EXISTING_TOP_LEVEL = {
    "debug",
    "resources",
}

REQUIRED_PATHS = (
    ".github/workflows/bmt-handoff.yml",
    ".github/workflows/build-and-test.yml",
    DEFAULT_CONFIG_ROOT,
    "tools/scripts/hooks/pre-commit-sync-gcp.sh",
)
# gcp/remote (DEFAULT_RUNTIME_ROOT) is optional: populated by sync; not required to exist for policy pass.


def _tracked_paths() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {(proc.stderr or proc.stdout).strip()}")
    root = Path.cwd()
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        if not (root / rel).exists():
            # Ignore tracked paths that are already removed in working tree.
            continue
        paths.append(rel)
    return paths


class RepoLayoutPolicy:
    """Validate top-level repository layout policy."""

    def run(self) -> int:
        root = Path.cwd()
        tracked = _tracked_paths()
        failures: list[str] = []

        top_level = {path.split("/", 1)[0] for path in tracked}
        unexpected_tracked = sorted(name for name in top_level if name not in ALLOWED_TRACKED_TOP_LEVEL)
        if unexpected_tracked:
            failures.append("Unexpected tracked top-level entries:")
            failures.extend([f"  - {name}" for name in unexpected_tracked])

        forbidden_tracked = sorted(path for path in tracked if path.startswith(FORBIDDEN_TRACKED_PREFIXES))
        if forbidden_tracked:
            failures.append("Forbidden tracked prefixes found:")
            failures.extend([f"  - {path}" for path in forbidden_tracked[:30]])
            if len(forbidden_tracked) > 30:
                failures.append(f"  ... and {len(forbidden_tracked) - 30} more")

        for rel in REQUIRED_PATHS:
            if not (root / rel).exists():
                failures.append(f"Missing required path: {rel}")

        forbidden_existing = sorted(name for name in FORBIDDEN_EXISTING_TOP_LEVEL if (root / name).exists())
        if forbidden_existing:
            failures.append("Forbidden top-level local directories exist:")
            failures.extend([f"  - {name}" for name in forbidden_existing])

        if failures:
            for line in failures:
                print(f"::error::{line}", file=sys.stderr)
            return 1

        print("Repository layout policy check passed")
        print("Tracked top-level entries are within policy.")
        print("No forbidden root clutter detected.")
        return 0


if __name__ == "__main__":
    raise SystemExit(RepoLayoutPolicy().run())

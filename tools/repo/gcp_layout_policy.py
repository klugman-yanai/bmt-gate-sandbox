#!/usr/bin/env python3
"""Validate canonical backend/ and benchmarks/ layout."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.shared.bucket_sync import matches
from tools.shared.layout_patterns import FORBIDDEN_CODE_PATTERNS, FORBIDDEN_RUNTIME_PATTERNS

# Root-level code files required in every layout (no project-specific paths).
SHARED_REQUIRED = (
    "pyproject.toml",
    "root_orchestrator.py",
    "vm_watcher.py",
    "scripts/startup_entrypoint.sh",
    "scripts/run_watcher.py",
    "scripts/validate_bucket_contract.py",
    "scripts/install_deps.py",
    "config/github_repos.json",
    "github/status_file.py",
)


def _discover_project_dirs(tracked_under_backend: set[str]) -> set[str]:
    """Return project dirs (paths under backend/) that have bmt_manager.py tracked."""
    project_dirs: set[str] = set()
    for rel in tracked_under_backend:
        if rel.endswith("bmt_manager.py"):
            prefix = rel[: -len("bmt_manager.py")].rstrip("/")
            if prefix:
                project_dirs.add(prefix)
    return project_dirs


def _required_code_files(tracked_under_backend: set[str]) -> tuple[str, ...]:
    """Build required code file list: SHARED + per-project bmt_manager.py and bmt_jobs.json."""
    required: list[str] = list(SHARED_REQUIRED)
    for project_dir in sorted(_discover_project_dirs(tracked_under_backend)):
        required.append(f"{project_dir}/bmt_manager.py")
        required.append(f"{project_dir}/bmt_jobs.json")
    return tuple(required)


# Legacy: discovery replaces fixed list. Tests that need a required list can call _required_code_files(tracked_set).
REQUIRED_CODE_FILES = _required_code_files


class GcpLayoutPolicy:
    """Validate backend/ and benchmarks/ layout."""

    def run(self) -> int:
        code_root = Path("backend")
        runtime_seed_root = Path("benchmarks")

        missing = False

        if not code_root.is_dir():
            print("::error::Missing backend/ directory", file=sys.stderr)
            return 1

        if not runtime_seed_root.exists():
            pass  # benchmarks/ optional (may be empty or created later)

        # Required = shared + per-project (discovered from tracked */bmt_manager.py)
        proc = subprocess.run(
            ["git", "ls-files", "--", "backend/"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path.cwd(),
        )
        tracked_under_backend = set()
        if proc.returncode == 0 and proc.stdout:
            for raw in proc.stdout.splitlines():
                line = raw.strip()
                if not line or not line.startswith("backend/"):
                    continue
                tracked_under_backend.add(line[len("backend/") :])  # drop "backend/" prefix

        required_code_files = _required_code_files(tracked_under_backend)
        for rel in required_code_files:
            p = code_root / rel
            if not p.exists():
                print(f"::error::Missing required code mirror object: {p}", file=sys.stderr)
                missing = True

        # Forbidden paths under backend/ (code mirror)
        forbidden_hits: list[str] = []
        for rel in sorted(tracked_under_backend):
            if matches(FORBIDDEN_CODE_PATTERNS, rel):
                forbidden_hits.append(rel)

        if forbidden_hits:
            print("::error::Forbidden runtime/generated paths found in backend/:", file=sys.stderr)
            for rel in forbidden_hits[:30]:
                print(f"  - {rel}", file=sys.stderr)
            if len(forbidden_hits) > 30:
                print(f"  ... and {len(forbidden_hits) - 30} more", file=sys.stderr)
            missing = True

        # Check benchmarks/ for forbidden patterns
        proc_benchmarks = subprocess.run(
            ["git", "ls-files", "--", "benchmarks/"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path.cwd(),
        )
        tracked_under_benchmarks = set()
        if proc_benchmarks.returncode == 0 and proc_benchmarks.stdout:
            for raw in proc_benchmarks.stdout.splitlines():
                line = raw.strip()
                if not line or not line.startswith("benchmarks/"):
                    continue
                tracked_under_benchmarks.add(line[len("benchmarks/") :])

        forbidden_runtime_hits = []
        for rel in sorted(tracked_under_benchmarks):
            if matches(FORBIDDEN_RUNTIME_PATTERNS, rel):
                forbidden_runtime_hits.append(rel)

        if forbidden_runtime_hits:
            print("::error::Forbidden generated/runtime paths found in benchmarks/:", file=sys.stderr)
            for rel in forbidden_runtime_hits[:30]:
                print(f"  - {rel}", file=sys.stderr)
            if len(forbidden_runtime_hits) > 30:
                print(f"  ... and {len(forbidden_runtime_hits) - 30} more", file=sys.stderr)
            missing = True

        if missing:
            return 1

        print("Layout policy check passed")
        print(f"Code root: {code_root}")
        print(f"Runtime seed root: {runtime_seed_root}")
        return 0


if __name__ == "__main__":
    raise SystemExit(GcpLayoutPolicy().run())

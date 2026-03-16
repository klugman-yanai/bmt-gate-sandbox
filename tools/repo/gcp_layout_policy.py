#!/usr/bin/env python3
"""Validate canonical gcp/ layout as a 1:1 bucket mirror."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.shared.bucket_sync import matches
from tools.shared.layout_patterns import ALLOWED_TOP_LEVEL, FORBIDDEN_CODE_PATTERNS, FORBIDDEN_RUNTIME_PATTERNS

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


def _discover_project_dirs(tracked_under_gcp: set[str]) -> set[str]:
    """Return project dirs (paths under image/) that have bmt_manager.py tracked."""
    code_prefix = "image/"
    project_dirs: set[str] = set()
    for rel in tracked_under_gcp:
        if not rel.startswith(code_prefix):
            continue
        rel_in_code = rel[len(code_prefix) :].lstrip("/")
        if rel_in_code.endswith("bmt_manager.py"):
            prefix = rel_in_code[: -len("bmt_manager.py")].rstrip("/")
            if prefix:
                project_dirs.add(prefix)
    return project_dirs


def _required_code_files(tracked_under_gcp: set[str]) -> tuple[str, ...]:
    """Build required code file list: SHARED + per-project bmt_manager.py and bmt_jobs.json."""
    required: list[str] = list(SHARED_REQUIRED)
    for project_dir in sorted(_discover_project_dirs(tracked_under_gcp)):
        required.append(f"{project_dir}/bmt_manager.py")
        required.append(f"{project_dir}/bmt_jobs.json")
    return tuple(required)


# Legacy: discovery replaces fixed list. Tests that need a required list can call _required_code_files(tracked_set).
REQUIRED_CODE_FILES = _required_code_files


class GcpLayoutPolicy:
    """Validate gcp/ layout as 1:1 bucket mirror."""

    def run(self) -> int:
        root = Path("gcp")
        code_root = root / "image"
        runtime_seed_root = root / "stage"

        missing = False

        if not root.is_dir():
            print("::error::Missing gcp/ directory", file=sys.stderr)
            return 1

        for path in (code_root, runtime_seed_root):
            if not path.exists():
                if path == runtime_seed_root:
                    pass  # remote/ optional (may be empty or created later)
                else:
                    print(f"::error::Missing canonical path: {path}", file=sys.stderr)
                    missing = True

        # Required = shared + per-project (discovered from tracked */bmt_manager.py)
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

        # Required files: warn only (avoids brittle failures when adding projects).
        required_code_files = _required_code_files(tracked_under_gcp)
        for rel in required_code_files:
            p = code_root / rel
            if not p.exists():
                print(f"::warning::Missing expected code mirror path: {p}", file=sys.stderr)

        # Forbidden paths under image (code mirror)
        code_prefix = "image/"
        forbidden_hits: list[str] = []
        for rel in sorted(tracked_under_gcp):
            if not rel.startswith(code_prefix):
                continue
            rel_in_code = rel[len(code_prefix) :]
            if matches(FORBIDDEN_CODE_PATTERNS, rel_in_code):
                forbidden_hits.append(rel_in_code)

        if forbidden_hits:
            print("::error::Forbidden runtime/generated paths found in gcp/image:", file=sys.stderr)
            for rel in forbidden_hits[:30]:
                print(f"  - {rel}", file=sys.stderr)
            if len(forbidden_hits) > 30:
                print(f"  ... and {len(forbidden_hits) - 30} more", file=sys.stderr)
            missing = True

        runtime_prefix = "stage/"
        forbidden_runtime_hits = []
        for rel in sorted(tracked_under_gcp):
            if not rel.startswith(runtime_prefix):
                continue
            rel_in_runtime = rel[len(runtime_prefix) :]
            if matches(FORBIDDEN_RUNTIME_PATTERNS, rel_in_runtime):
                # Allow .keep placeholders under outputs/inputs so empty dirs can be tracked
                if rel_in_runtime.endswith("/.keep") or rel_in_runtime == ".keep":
                    continue
                forbidden_runtime_hits.append(rel_in_runtime)

        if forbidden_runtime_hits:
            print("::error::Forbidden generated/runtime paths found in gcp/stage:", file=sys.stderr)
            for rel in forbidden_runtime_hits[:30]:
                print(f"  - {rel}", file=sys.stderr)
            if len(forbidden_runtime_hits) > 30:
                print(f"  ... and {len(forbidden_runtime_hits) - 30} more", file=sys.stderr)
            missing = True

        unexpected_top_level = sorted(
            entry.name
            for entry in root.iterdir()
            if entry.name not in ALLOWED_TOP_LEVEL and not entry.name.startswith(".") and entry.name != "__pycache__"
        )
        if unexpected_top_level:
            print(
                "::error::gcp/ must only contain allowed top-level entries (e.g. image/, remote/, local/).",
                file=sys.stderr,
            )
            for name in unexpected_top_level:
                print(f"  - unexpected: gcp/{name}", file=sys.stderr)
            missing = True

        if missing:
            return 1

        print("GCP layout policy check passed")
        print(f"Code mirror root (image): {code_root}")
        print(f"Staging area root (stage): {runtime_seed_root}")
        print(f"Top-level entries: {', '.join(sorted(ALLOWED_TOP_LEVEL))}")
        return 0


if __name__ == "__main__":
    raise SystemExit(GcpLayoutPolicy().run())

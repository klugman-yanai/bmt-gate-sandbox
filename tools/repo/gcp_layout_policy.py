#!/usr/bin/env python3
"""Validate canonical backend/ + benchmarks/ layout as a 1:1 bucket mirror."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.shared.bucket_sync import matches
from tools.shared.layout_patterns import FORBIDDEN_CODE_PATTERNS, FORBIDDEN_RUNTIME_PATTERNS

SHARED_REQUIRED = (
    "pyproject.toml",
    "main.py",
    "runtime/__init__.py",
)


class GcpLayoutPolicy:
    """Validate backend/ + benchmarks/ layout as 1:1 bucket mirror."""

    def run(self) -> int:
        code_root = Path("backend")
        runtime_seed_root = Path("benchmarks")

        missing = False

        if not code_root.is_dir():
            print("::error::Missing backend/ directory", file=sys.stderr)
            missing = True

        # benchmarks/ is optional (may be empty or created later via sync)

        # Required shared files for the Cloud Run runtime package.
        proc = subprocess.run(
            ["git", "ls-files", "--", "backend/", "benchmarks/"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path.cwd(),
        )
        tracked_under_backend: set[str] = set()
        tracked_under_benchmarks: set[str] = set()
        if proc.returncode == 0 and proc.stdout:
            for raw in proc.stdout.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("backend/"):
                    tracked_under_backend.add(line[len("backend/"):])
                elif line.startswith("benchmarks/"):
                    tracked_under_benchmarks.add(line[len("benchmarks/"):])

        for rel in SHARED_REQUIRED:
            p = code_root / rel
            if not p.exists():
                print(f"::warning::Missing expected code mirror path: {p}", file=sys.stderr)

        # Forbidden paths under backend (code mirror)
        forbidden_hits: list[str] = []
        for rel in sorted(tracked_under_backend):
            if matches(FORBIDDEN_CODE_PATTERNS, rel):
                forbidden_hits.append(rel)

        if forbidden_hits:
            print("::error::Forbidden runtime/generated paths found in backend:", file=sys.stderr)
            for rel in forbidden_hits[:30]:
                print(f"  - {rel}", file=sys.stderr)
            if len(forbidden_hits) > 30:
                print(f"  ... and {len(forbidden_hits) - 30} more", file=sys.stderr)
            missing = True

        forbidden_runtime_hits = []
        for rel in sorted(tracked_under_benchmarks):
            if matches(FORBIDDEN_RUNTIME_PATTERNS, rel):
                # Allow .keep placeholders under outputs/inputs so empty dirs can be tracked
                if rel.endswith("/.keep") or rel == ".keep":
                    continue
                forbidden_runtime_hits.append(rel)

        if forbidden_runtime_hits:
            print("::error::Forbidden generated/runtime paths found in benchmarks:", file=sys.stderr)
            for rel in forbidden_runtime_hits[:30]:
                print(f"  - {rel}", file=sys.stderr)
            if len(forbidden_runtime_hits) > 30:
                print(f"  ... and {len(forbidden_runtime_hits) - 30} more", file=sys.stderr)
            missing = True

        if missing:
            return 1

        print("Layout policy check passed")
        print(f"Code mirror root: {code_root}")
        print(f"Staging area root: {runtime_seed_root}")
        return 0


if __name__ == "__main__":
    raise SystemExit(GcpLayoutPolicy().run())

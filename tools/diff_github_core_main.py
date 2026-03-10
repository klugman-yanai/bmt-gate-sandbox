#!/usr/bin/env python3
"""Diff .github BMT surface between bmt-gcloud and core-main to manage drift.

Usage (from bmt-gcloud repo root):
  CORE_MAIN=/path/to/core-main uv run python tools/diff_github_core_main.py
  # or
  just diff-core-main

See docs/drift-core-main-vs-bmt-gcloud.md for how to interpret the diff.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Files under .github that should match between core-main and bmt-gcloud (same path).
BMT_SURFACE_FILES = [
    "workflows/bmt.yml",
    "actions/bmt-prepare/action.yml",
    "actions/bmt-classify-handoff/action.yml",
    "actions/bmt-handoff-run/action.yml",
    "actions/bmt-write-summary/action.yml",
    "actions/bmt-failure-fallback/action.yml",
    "actions/setup-gcp-uv/action.yml",
]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    core_main = os.environ.get("CORE_MAIN")
    if not core_main:
        for candidate in [repo_root / ".." / "core-main", repo_root / ".." / "kardome" / "core-main"]:
            if (candidate.resolve() / ".github" / "workflows" / "bmt.yml").exists():
                core_main = str(candidate.resolve())
                break
    if not core_main or not Path(core_main).is_dir():
        print("CORE_MAIN not set or not a directory. Set it to your core-main repo path.", file=sys.stderr)
        print("  export CORE_MAIN=/path/to/kardome/core-main", file=sys.stderr)
        print("  just diff-core-main  # or: uv run python tools/diff_github_core_main.py", file=sys.stderr)
        return 1

    core = Path(core_main)
    bmt = repo_root
    exit_code = 0

    print("=== Comparing .github (bmt-gcloud vs core-main) ===\n")
    print(f"  bmt-gcloud: {bmt}\n  core-main:  {core}\n")

    for rel in BMT_SURFACE_FILES:
        p_core = core / ".github" / rel
        p_bmt = bmt / ".github" / rel
        if not p_core.exists():
            print(f"  [only in bmt-gcloud] .github/{rel}")
            continue
        if not p_bmt.exists():
            print(f"  [only in core-main] .github/{rel}")
            exit_code = 1
            continue
        ret = subprocess.run(
            ["diff", "-u", str(p_core), str(p_bmt)],
            capture_output=True,
            text=True,
        )
        if ret.returncode != 0:
            print(f"=== .github/{rel} ===")
            print(ret.stdout)
            if ret.stderr:
                print(ret.stderr, file=sys.stderr)
            exit_code = 1

    # Recursive diff for .github/bmt (exclude secrets and cache)
    bmt_dir = bmt / ".github" / "bmt"
    core_bmt = core / ".github" / "bmt"
    if core_bmt.is_dir() and bmt_dir.is_dir():
        ret = subprocess.run(
            [
                "diff",
                "-rq",
                "--exclude=*.pem",
                "--exclude=__pycache__",
                "--exclude=.ruff_cache",
                "--exclude=*.egg-info",
                "--exclude=.gitignore",
                str(core_bmt),
                str(bmt_dir),
            ],
            capture_output=True,
            text=True,
        )
        if ret.returncode != 0:
            print("=== .github/bmt (summary) ===")
            print(ret.stdout)
            exit_code = 1
        ret2 = subprocess.run(
            [
                "diff",
                "-r",
                "--exclude=*.pem",
                "--exclude=__pycache__",
                "--exclude=.ruff_cache",
                "--exclude=*.egg-info",
                "--exclude=.gitignore",
                str(core_bmt),
                str(bmt_dir),
            ],
            capture_output=True,
            text=True,
        )
        if ret2.returncode != 0:
            print("=== .github/bmt (content diff) ===")
            print(ret2.stdout)

    if exit_code == 0:
        print("No differences in BMT surface files.")
    else:
        print("\nSee docs/drift-core-main-vs-bmt-gcloud.md for how to resolve drift.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

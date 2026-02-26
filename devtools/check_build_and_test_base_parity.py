#!/usr/bin/env python3
"""Validate that build-and-test.yml keeps an immutable prod base block."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path


BEGIN_BASE = "# BEGIN PROD-IMMUTABLE BASE (synced from original_build-and-test.yml)"
END_BASE = "# END PROD-IMMUTABLE BASE (synced from original_build-and-test.yml)"
BEGIN_EXT = "# BEGIN BMT EXTENSION (append-only)"


def _find_unique_marker(lines: list[str], marker: str, file_label: str) -> int:
    hits = [idx for idx, line in enumerate(lines) if line == marker]
    if len(hits) != 1:
        raise ValueError(f"{file_label}: expected exactly one marker '{marker}', found {len(hits)}")
    return hits[0]


def _first_non_empty_index(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        if line.strip():
            return idx
    return None


def check_parity(workflow_path: Path, original_path: Path) -> int:
    workflow_lines = workflow_path.read_text(encoding="utf-8").splitlines()
    original_lines = original_path.read_text(encoding="utf-8").splitlines()

    begin_idx = _find_unique_marker(workflow_lines, BEGIN_BASE, str(workflow_path))
    end_idx = _find_unique_marker(workflow_lines, END_BASE, str(workflow_path))
    ext_idx = _find_unique_marker(workflow_lines, BEGIN_EXT, str(workflow_path))

    if not (begin_idx < end_idx < ext_idx):
        raise ValueError(
            f"{workflow_path}: marker order must be BEGIN_BASE < END_BASE < BEGIN_EXT, "
            f"got {begin_idx}, {end_idx}, {ext_idx}"
        )

    first_non_empty = _first_non_empty_index(workflow_lines)
    if first_non_empty is None or first_non_empty != begin_idx:
        raise ValueError(
            f"{workflow_path}: first non-empty line must be '{BEGIN_BASE}' at line {begin_idx + 1}"
        )

    pre_base_payload = workflow_lines[begin_idx + 1 : end_idx]
    if pre_base_payload != original_lines:
        diff = "\n".join(
            difflib.unified_diff(
                original_lines,
                pre_base_payload,
                fromfile=str(original_path),
                tofile=f"{workflow_path} (base block)",
                lineterm="",
            )
        )
        raise ValueError(
            "Prod-immutable base block does not match original_build-and-test.yml.\n"
            + (diff if diff else "(no diff produced)")
        )

    between_markers = workflow_lines[end_idx + 1 : ext_idx]
    if any(line.strip() for line in between_markers):
        raise ValueError(
            f"{workflow_path}: only blank lines are allowed between END_BASE and BEGIN_EXT markers"
        )

    print(
        "OK: build-and-test base parity validated "
        f"(base lines={len(pre_base_payload)}, extension lines={len(workflow_lines) - ext_idx - 1})"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workflow",
        default=".github/workflows/build-and-test.yml",
        help="Workflow file to validate",
    )
    parser.add_argument(
        "--original",
        default="original_build-and-test.yml",
        help="Canonical production baseline file",
    )
    args = parser.parse_args()

    workflow_path = Path(args.workflow)
    original_path = Path(args.original)
    if not workflow_path.is_file():
        print(f"ERROR: workflow file not found: {workflow_path}", file=sys.stderr)
        return 1
    if not original_path.is_file():
        print(f"ERROR: original baseline file not found: {original_path}", file=sys.stderr)
        return 1

    try:
        return check_parity(workflow_path, original_path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Test utilities — moved from tests/_support/testutils.py.

Import from here in new code. The old path (tests/_support/testutils) remains
as a re-export shim for backward compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, Literal, overload


def combined_output(proc: CompletedProcess[str]) -> str:
    """Return stderr+stdout in one stable string for error assertions."""
    return f"{proc.stderr}\n{proc.stdout}"


def read_github_output(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines written to GITHUB_OUTPUT."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


@overload
def decode_output_json(outputs: dict[str, str], key: Literal["matrix"]) -> dict[str, list[dict[str, str]]]: ...


@overload
def decode_output_json(outputs: dict[str, str], key: str) -> object: ...


def decode_output_json(outputs: dict[str, str], key: str) -> object:
    """Decode JSON payload from parsed GITHUB_OUTPUT by key."""
    if key not in outputs:
        raise AssertionError(f"Missing output key: {key}")
    return json.loads(outputs[key])


def assert_github_matrix_include_shape(matrix: dict[str, Any]) -> None:
    """Assert ``matrix`` matches what CI integration tests expect for ``matrix`` JSON."""
    if "include" not in matrix:
        raise AssertionError("matrix missing 'include' key")
    include = matrix["include"]
    if not isinstance(include, list):
        raise TypeError("matrix.include must be a list")
    if len(include) == 0:
        raise AssertionError("matrix.include is empty")
    for entry in include:
        if not isinstance(entry, dict):
            raise TypeError("matrix include entry must be an object")
        if "project" not in entry:
            raise AssertionError("matrix entry missing 'project'")
        if "bmt_id" not in entry:
            raise AssertionError("matrix entry missing 'bmt_id'")


def assert_matrix_projects_subset(matrix: dict[str, Any], allowed: set[str]) -> None:
    """Assert every ``include`` entry's ``project`` is in ``allowed`` (filter sanity)."""
    include = matrix.get("include")
    if not isinstance(include, list):
        raise TypeError("matrix.include must be a list")
    for raw in include:
        if not isinstance(raw, dict):
            continue
        entry: dict[str, Any] = raw
        proj = entry.get("project")
        if proj not in allowed:
            raise AssertionError(f"Filter leaked projects: {proj!r} not in {allowed!r}")

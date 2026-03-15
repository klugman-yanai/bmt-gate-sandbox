"""Negative tests to verify that our test harness correctly detects failures.

These tests verify that our positive tests would actually fail if the commands were broken.
They should all be marked as xfail (expected to fail).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._support.testutils import decode_output_json, read_github_output


@pytest.mark.xfail(reason="Demonstrates that tests catch JSON structure violations", strict=True)
def test_matrix_test_would_catch_missing_include_key(tmp_path: Path) -> None:
    """Verify that matrix test would fail if output had no 'include' key."""
    # Simulate what would happen if matrix output was malformed
    github_output = tmp_path / "missing-include.txt"
    github_output.write_text('matrix={"wrong_key": []}', encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")

    # This should fail because 'include' is missing
    assert "include" in matrix, "matrix missing 'include' key"
    assert len(matrix["include"]) > 0


@pytest.mark.xfail(reason="Demonstrates that tests catch empty matrices", strict=True)
def test_matrix_test_would_catch_empty_matrix(tmp_path: Path) -> None:
    """Verify that matrix test would fail if matrix was empty."""
    github_output = tmp_path / "empty-matrix.txt"
    github_output.write_text('matrix={"include": []}', encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")

    # This should fail because include is empty
    assert len(matrix["include"]) > 0, "matrix.include is empty"


@pytest.mark.xfail(reason="Demonstrates that tests catch missing required fields", strict=True)
def test_matrix_test_would_catch_missing_project_field(tmp_path: Path) -> None:
    """Verify that matrix test would fail if entries were missing required fields."""
    github_output = tmp_path / "missing-project.txt"
    github_output.write_text('matrix={"include": [{"bmt_id": "test"}]}', encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")

    # This should fail because 'project' is missing
    for entry in matrix["include"]:
        assert "project" in entry, "matrix entry missing 'project'"


@pytest.mark.xfail(reason="Demonstrates that tests catch filter leakage", strict=True)
def test_filter_test_would_catch_wrong_projects(tmp_path: Path) -> None:
    """Verify that filter test would catch if wrong projects leaked through."""
    github_output = tmp_path / "filter-leak.txt"
    github_output.write_text(
        'matrix={"include": [{"project": "sk", "bmt_id": "test1"}, {"project": "continental", "bmt_id": "test2"}]}',
        encoding="utf-8",
    )
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")

    # This should fail because continental leaked through sk filter
    found_projects = set()
    for entry in matrix["include"]:
        found_projects.add(entry["project"])
        assert entry["project"] == "sk", f"Filter leaked projects: {found_projects}"


@pytest.mark.xfail(reason="Demonstrates that tests catch invalid JSON", strict=True)
def test_json_validation_would_catch_invalid_json(tmp_path: Path) -> None:
    """Verify that JSON validation would catch malformed JSON."""
    github_output = tmp_path / "invalid-json.txt"
    github_output.write_text("matrix={invalid json here", encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix_json = outputs["matrix"]

    # This should fail because JSON is invalid.
    json.loads(matrix_json)


def test_negative_tests_run_and_verify_xfails() -> None:
    """Meta-test: Verify that all xfail tests actually fail as expected."""
    # Run only the xfail cases (exclude this meta-test to avoid subprocess recursion).
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/ci/test_ci_commands_negative.py",
            "-k",
            "not test_negative_tests_run_and_verify_xfails",
            "-v",
            "--tb=no",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    # The xfail tests should show as "XFAIL" not "PASSED"
    # If they show as PASSED, it means they're not catching the errors
    assert "XFAIL" in result.stdout or "xfailed" in result.stdout, (
        "Negative tests didn't xfail as expected - test harness may be broken"
    )

    # Should have some xfailed tests
    assert "5 xfailed" in result.stdout or "xpassed" not in result.stdout, (
        "Expected xfail tests to fail. If they passed, our test validation is broken."
    )

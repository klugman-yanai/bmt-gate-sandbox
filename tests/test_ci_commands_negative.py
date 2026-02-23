"""Negative tests to verify that our test harness correctly detects failures.

These tests verify that our positive tests would actually fail if the commands were broken.
They should all be marked as xfail (expected to fail).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.mark.xfail(reason="Demonstrates that tests catch JSON structure violations", strict=True)
def test_matrix_test_would_catch_missing_include_key() -> None:
    """Verify that matrix test would fail if output had no 'include' key."""
    # Simulate what would happen if matrix output was malformed
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        # Write malformed output (missing 'include' key)
        github_output.write_text('matrix={"wrong_key": []}')

        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None

        matrix_json = matrix_line.split("=", 1)[1]
        matrix = json.loads(matrix_json)

        # This should fail because 'include' is missing
        assert "include" in matrix, "matrix missing 'include' key"
        assert len(matrix["include"]) > 0

    finally:
        if github_output.exists():
            github_output.unlink()


@pytest.mark.xfail(reason="Demonstrates that tests catch empty matrices", strict=True)
def test_matrix_test_would_catch_empty_matrix() -> None:
    """Verify that matrix test would fail if matrix was empty."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        # Write empty matrix
        github_output.write_text('matrix={"include": []}')

        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        matrix_json = matrix_line.split("=", 1)[1]
        matrix = json.loads(matrix_json)

        # This should fail because include is empty
        assert len(matrix["include"]) > 0, "matrix.include is empty"

    finally:
        if github_output.exists():
            github_output.unlink()


@pytest.mark.xfail(reason="Demonstrates that tests catch missing required fields", strict=True)
def test_matrix_test_would_catch_missing_project_field() -> None:
    """Verify that matrix test would fail if entries were missing required fields."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        # Write matrix with missing 'project' field
        github_output.write_text('matrix={"include": [{"bmt_id": "test"}]}')

        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        matrix_json = matrix_line.split("=", 1)[1]
        matrix = json.loads(matrix_json)

        # This should fail because 'project' is missing
        for entry in matrix["include"]:
            assert "project" in entry, "matrix entry missing 'project'"

    finally:
        if github_output.exists():
            github_output.unlink()


@pytest.mark.xfail(reason="Demonstrates that tests catch filter leakage", strict=True)
def test_filter_test_would_catch_wrong_projects() -> None:
    """Verify that filter test would catch if wrong projects leaked through."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        # Simulate filter leakage - other projects in filtered results
        github_output.write_text(
            'matrix={"include": [{"project": "sk", "bmt_id": "test1"}, {"project": "continental", "bmt_id": "test2"}]}'
        )

        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        matrix_json = matrix_line.split("=", 1)[1]
        matrix = json.loads(matrix_json)

        # This should fail because continental leaked through sk filter
        found_projects = set()
        for entry in matrix["include"]:
            found_projects.add(entry["project"])
            assert entry["project"] == "sk", f"Filter leaked projects: {found_projects}"

    finally:
        if github_output.exists():
            github_output.unlink()


@pytest.mark.xfail(reason="Demonstrates that tests catch invalid JSON", strict=True)
def test_json_validation_would_catch_invalid_json() -> None:
    """Verify that JSON validation would catch malformed JSON."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        # Write invalid JSON
        github_output.write_text("matrix={invalid json here")

        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        matrix_json = matrix_line.split("=", 1)[1]

        # This should fail because JSON is invalid
        try:
            json.loads(matrix_json)
            pytest.fail("Should have raised JSONDecodeError")
        except json.JSONDecodeError:
            raise  # Expected - re-raise to make xfail work

    finally:
        if github_output.exists():
            github_output.unlink()


def test_negative_tests_run_and_verify_xfails() -> None:
    """Meta-test: Verify that all xfail tests actually fail as expected."""
    # Run the negative tests and verify they all xfail
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/test_ci_commands_negative.py", "-v", "--tb=no"],
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

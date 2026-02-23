"""Integration tests for CI commands."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


def test_matrix_command_runs() -> None:
    """Test that the matrix command runs without error."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        result = subprocess.run(
            [
                "python",
                ".github/scripts/ci_driver.py",
                "matrix",
                "--config-root",
                "remote",
                "--project-filter",
                "",
                "--github-output",
                str(github_output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Command failed: {result.stderr}"

        # Verify output file was written
        assert github_output.exists(), "GITHUB_OUTPUT file not created"
        content = github_output.read_text()
        assert "matrix=" in content, "matrix key not found in output"

        # Parse and validate matrix JSON
        matrix_line = next(line for line in content.split("\n") if line.startswith("matrix="))
        matrix_json = matrix_line.split("=", 1)[1]
        matrix = json.loads(matrix_json)

        assert "include" in matrix, "matrix missing 'include' key"
        assert isinstance(matrix["include"], list), "matrix.include is not a list"
        assert len(matrix["include"]) > 0, "matrix is empty"

        # Validate each entry has required fields
        for entry in matrix["include"]:
            assert "project" in entry, "matrix entry missing 'project'"
            assert "bmt_id" in entry, "matrix entry missing 'bmt_id'"

    finally:
        if github_output.exists():
            github_output.unlink()


def test_matrix_command_with_filter() -> None:
    """Test that the matrix command respects project filter."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        result = subprocess.run(
            [
                "python",
                ".github/scripts/ci_driver.py",
                "matrix",
                "--config-root",
                "remote",
                "--project-filter",
                "sk",
                "--github-output",
                str(github_output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Command failed: {result.stderr}"

        # Parse matrix
        content = github_output.read_text()
        matrix_line = next(line for line in content.split("\n") if line.startswith("matrix="))
        matrix_json = matrix_line.split("=", 1)[1]
        matrix = json.loads(matrix_json)

        # All entries should be for 'sk' project
        for entry in matrix["include"]:
            assert entry["project"] == "sk", f"Unexpected project: {entry['project']}"

    finally:
        if github_output.exists():
            github_output.unlink()


def test_upload_runner_command_help() -> None:
    """Test that upload-runner command is registered and shows help."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "upload-runner", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--bucket" in result.stdout
    assert "--runner-dir" in result.stdout
    assert "--project" in result.stdout
    assert "--preset" in result.stdout


def test_trigger_command_help() -> None:
    """Test that trigger command is registered and shows help."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "trigger", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--config-root" in result.stdout
    assert "--bucket" in result.stdout
    assert "--matrix-json" in result.stdout


def test_start_vm_command_help() -> None:
    """Test that start-vm command is registered and shows help."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "start-vm", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    # start-vm reads from env vars, so just check it runs


def test_wait_command_help() -> None:
    """Test that wait command is registered and shows help."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "wait", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--config-root" in result.stdout
    assert "--bucket" in result.stdout


def test_gate_command_help() -> None:
    """Test that gate command is registered and shows help."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "gate", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--decision" in result.stdout
    assert "--pass-count" in result.stdout

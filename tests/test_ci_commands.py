"""Integration tests for CI commands.

These tests verify that CI commands work correctly and fail appropriately.
They use real config files to ensure end-to-end correctness.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def test_matrix_command_runs() -> None:
    """Test that the matrix command runs without error and produces valid output."""
    # CRITICAL: Verify config files exist before running test
    config_root = Path("remote")
    assert config_root.exists(), f"Config root {config_root} does not exist - test environment broken"
    assert (config_root / "bmt_projects.json").exists(), "bmt_projects.json missing - cannot test"

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

        # CRITICAL: Command must succeed
        assert result.returncode == 0, f"Command failed with rc={result.returncode}: {result.stderr}"

        # CRITICAL: Output file must exist and be non-empty
        assert github_output.exists(), "GITHUB_OUTPUT file not created"
        content = github_output.read_text()
        assert len(content.strip()) > 0, "GITHUB_OUTPUT is empty"
        assert "matrix=" in content, "matrix key not found in output"

        # CRITICAL: Parse and validate matrix JSON structure
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None, "No line starting with 'matrix=' found"

        matrix_json = matrix_line.split("=", 1)[1]
        assert len(matrix_json) > 0, "Matrix JSON is empty"

        matrix = json.loads(matrix_json)
        assert isinstance(matrix, dict), f"Matrix is not a dict: {type(matrix)}"
        assert "include" in matrix, "matrix missing 'include' key"
        assert isinstance(matrix["include"], list), f"matrix.include is not a list: {type(matrix['include'])}"
        assert len(matrix["include"]) > 0, "matrix.include is empty - no BMT jobs found"

        # CRITICAL: Validate each entry has required fields with correct types
        for idx, entry in enumerate(matrix["include"]):
            assert isinstance(entry, dict), f"Entry {idx} is not a dict: {type(entry)}"
            assert "project" in entry, f"Entry {idx} missing 'project': {entry}"
            assert "bmt_id" in entry, f"Entry {idx} missing 'bmt_id': {entry}"
            assert isinstance(entry["project"], str), f"Entry {idx} project is not string: {type(entry['project'])}"
            assert isinstance(entry["bmt_id"], str), f"Entry {idx} bmt_id is not string: {type(entry['bmt_id'])}"
            assert len(entry["project"]) > 0, f"Entry {idx} has empty project"
            assert len(entry["bmt_id"]) > 0, f"Entry {idx} has empty bmt_id"

        # CRITICAL: Verify we found the expected SK project (our known BMT-enabled project)
        projects = {entry["project"] for entry in matrix["include"]}
        assert "sk" in projects, f"Expected 'sk' project not found in matrix. Found: {projects}"

    finally:
        if github_output.exists():
            github_output.unlink()


def test_matrix_command_with_filter() -> None:
    """Test that the matrix command respects project filter and ONLY returns filtered projects."""
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

        # CRITICAL: Command must succeed
        assert result.returncode == 0, f"Command failed with rc={result.returncode}: {result.stderr}"

        # Parse and validate matrix
        content = github_output.read_text()
        assert len(content.strip()) > 0, "Output is empty"

        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None, "No matrix= line found"

        matrix_json = matrix_line.split("=", 1)[1]
        matrix = json.loads(matrix_json)

        assert "include" in matrix, "matrix missing 'include'"
        assert len(matrix["include"]) > 0, "Filtered matrix is empty - should have sk entries"

        # CRITICAL: ALL entries must be for 'sk' project - no leakage
        found_projects = set()
        for idx, entry in enumerate(matrix["include"]):
            found_projects.add(entry["project"])
            assert entry["project"] == "sk", (
                f"Entry {idx} has wrong project: {entry['project']} (expected 'sk'). "
                f"Filter leaked projects: {found_projects}"
            )

        # CRITICAL: Verify we got exactly what we asked for
        assert found_projects == {"sk"}, f"Expected only 'sk', found: {found_projects}"

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


def test_wait_handshake_command_help() -> None:
    """Test that wait-handshake command is registered and shows help."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "wait-handshake", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--bucket" in result.stdout
    assert "--workflow-run-id" in result.stdout


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


def test_matrix_command_fails_without_github_output() -> None:
    """Test that matrix command fails when GITHUB_OUTPUT is missing."""
    result = subprocess.run(
        [
            "python",
            ".github/scripts/ci_driver.py",
            "matrix",
            "--config-root",
            "remote",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    # CRITICAL: Must fail when required env var is missing
    assert result.returncode != 0, "Command should fail without GITHUB_OUTPUT"
    assert "GITHUB_OUTPUT is required" in result.stderr or "GITHUB_OUTPUT" in str(
        result.stderr + result.stdout
    ), f"Error message unclear: {result.stderr}"


def test_matrix_command_fails_with_invalid_config_root() -> None:
    """Test that matrix command fails with non-existent config root."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        result = subprocess.run(
            [
                "python",
                ".github/scripts/ci_driver.py",
                "matrix",
                "--config-root",
                "/nonexistent/path/to/nowhere",
                "--github-output",
                str(github_output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        # CRITICAL: Must fail with invalid config path
        assert result.returncode != 0, "Command should fail with invalid config-root"

    finally:
        if github_output.exists():
            github_output.unlink()


def test_all_commands_are_registered() -> None:
    """Test that all expected commands are registered in the CLI."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    # CRITICAL: All commands must be present
    expected_commands = ["matrix", "trigger", "start-vm", "upload-runner", "wait-handshake", "wait", "gate"]
    for cmd in expected_commands:
        assert cmd in result.stdout, f"Command '{cmd}' not registered in CLI"


def test_unknown_command_fails() -> None:
    """Test that unknown commands fail appropriately."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "nonexistent-command"],
        check=False,
        capture_output=True,
        text=True,
    )

    # CRITICAL: Must fail on unknown command
    assert result.returncode != 0, "Should fail on unknown command"


def test_matrix_output_is_valid_json() -> None:
    """Test that matrix command produces valid, parseable JSON."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        subprocess.run(
            [
                "python",
                ".github/scripts/ci_driver.py",
                "matrix",
                "--config-root",
                "remote",
                "--github-output",
                str(github_output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        content = github_output.read_text()
        matrix_line = next(line for line in content.split("\n") if line.startswith("matrix="))
        matrix_json = matrix_line.split("=", 1)[1]

        # CRITICAL: Must be valid JSON (json.loads will raise on invalid JSON)
        try:
            parsed = json.loads(matrix_json)
        except json.JSONDecodeError as e:
            pytest.fail(f"Matrix output is not valid JSON: {e}\nGot: {matrix_json}")

        # CRITICAL: Must be a dict with include array
        assert isinstance(parsed, dict), f"Parsed matrix is not a dict: {type(parsed)}"
        assert "include" in parsed, "Matrix missing 'include' key"

    finally:
        if github_output.exists():
            github_output.unlink()


def test_upload_runner_fails_with_missing_required_args() -> None:
    """Test that upload-runner fails when required arguments are missing."""
    result = subprocess.run(
        ["python", ".github/scripts/ci_driver.py", "upload-runner"],
        check=False,
        capture_output=True,
        text=True,
    )

    # CRITICAL: Must fail without required args
    assert result.returncode != 0, "Should fail without required arguments"
    # Should mention missing required options
    assert (
        "Missing option" in result.stderr
        or "required" in result.stderr.lower()
        or "Error" in result.stderr
    ), f"Error message unclear: {result.stderr}"


def test_trigger_fails_with_invalid_matrix_json() -> None:
    """Test that trigger command fails with invalid matrix JSON."""
    # Set minimal env vars to avoid early failures
    env = os.environ.copy()
    env["GCS_BUCKET"] = "test-bucket"

    result = subprocess.run(
        [
            "python",
            ".github/scripts/ci_driver.py",
            "trigger",
            "--config-root",
            "remote",
            "--bucket",
            "test-bucket",
            "--matrix-json",
            "not-valid-json",
            "--run-context",
            "dev",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    # CRITICAL: Must fail with invalid JSON
    assert result.returncode != 0, "Should fail with invalid matrix JSON"

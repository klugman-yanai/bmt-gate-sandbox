"""Integration tests for CI commands via bmt entry point subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def _run(
    cmd: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["uv", "run", "bmt", cmd],
        check=check,
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_matrix_command_runs() -> None:
    config_root = Path("remote/code")
    assert config_root.exists()
    assert (config_root / "bmt_projects.json").exists()

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)

    try:
        result = _run("matrix", env={"BMT_CONFIG_ROOT": "remote/code", "GITHUB_OUTPUT": str(github_output)})
        assert result.returncode == 0
        content = github_output.read_text()
        assert "matrix=" in content
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None
        matrix = json.loads(matrix_line.split("=", 1)[1])
        assert "include" in matrix
        assert len(matrix["include"]) > 0
        for entry in matrix["include"]:
            assert "project" in entry and "bmt_id" in entry
        assert "sk" in {e["project"] for e in matrix["include"]}
    finally:
        if github_output.exists():
            github_output.unlink()


def test_matrix_command_with_filter() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        result = _run(
            "matrix",
            env={"BMT_CONFIG_ROOT": "remote/code", "BMT_PROJECTS": "sk", "GITHUB_OUTPUT": str(github_output)},
        )
        assert result.returncode == 0
        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None
        matrix = json.loads(matrix_line.split("=", 1)[1])
        assert {e["project"] for e in matrix["include"]} == {"sk"}
    finally:
        if github_output.exists():
            github_output.unlink()


def test_matrix_command_with_all_filter() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        result = _run(
            "matrix",
            env={
                "BMT_CONFIG_ROOT": "remote/code",
                "BMT_PROJECTS": "all",
                "GITHUB_OUTPUT": str(github_output),
            },
        )
        assert result.returncode == 0
        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None
        matrix = json.loads(matrix_line.split("=", 1)[1])
        assert "sk" in {e["project"] for e in matrix["include"]}
    finally:
        if github_output.exists():
            github_output.unlink()


def test_matrix_command_with_json_array_filter() -> None:
    """BMT_PROJECTS accepts a JSON array e.g. [\"sk\"] or [\"SK\"] (normalized to lowercase)."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        result = _run(
            "matrix",
            env={"BMT_CONFIG_ROOT": "remote/code", "BMT_PROJECTS": '["sk"]', "GITHUB_OUTPUT": str(github_output)},
        )
        assert result.returncode == 0
        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None
        matrix = json.loads(matrix_line.split("=", 1)[1])
        assert {e["project"] for e in matrix["include"]} == {"sk"}
    finally:
        if github_output.exists():
            github_output.unlink()


def test_matrix_command_with_unsupported_filter_is_non_fatal() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        result = _run(
            "matrix",
            env={
                "BMT_CONFIG_ROOT": "remote/code",
                "BMT_PROJECTS": "does-not-exist",
                "GITHUB_OUTPUT": str(github_output),
            },
        )
        assert result.returncode == 0
        assert "No supported project+BMT rows found" in result.stdout
        content = github_output.read_text()
        matrix_line = next((line for line in content.split("\n") if line.startswith("matrix=")), None)
        assert matrix_line is not None
        assert json.loads(matrix_line.split("=", 1)[1])["include"] == []
    finally:
        if github_output.exists():
            github_output.unlink()


def test_filter_supported_matrix_success() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        runner_matrix = {"include": [{"project": "sk"}, {"project": "missing"}]}
        full_matrix = {"include": [{"project": "sk", "bmt_id": "sk-bmt"}]}
        result = _run(
            "filter-supported-matrix",
            env={
                "GITHUB_OUTPUT": str(github_output),
                "RUNNER_MATRIX": json.dumps(runner_matrix),
                "FULL_MATRIX": json.dumps(full_matrix),
                "ACCEPTED_PROJECTS": json.dumps(["sk"]),
            },
        )
        assert result.returncode == 0
        content = github_output.read_text()
        matrix_line = next((line for line in content.splitlines() if line.startswith("matrix=")), None)
        has_legs_line = next((line for line in content.splitlines() if line.startswith("has_legs=")), None)
        assert matrix_line is not None
        assert has_legs_line == "has_legs=true"
        assert json.loads(matrix_line.split("=", 1)[1])["include"] == [{"project": "sk", "bmt_id": "sk-bmt"}]
    finally:
        if github_output.exists():
            github_output.unlink()


def test_filter_supported_matrix_fails_when_no_uploaded_supported_projects() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        runner_matrix = {"include": [{"project": "sk"}]}
        full_matrix = {"include": [{"project": "sk", "bmt_id": "sk-bmt"}]}
        result = _run(
            "filter-supported-matrix",
            env={
                "GITHUB_OUTPUT": str(github_output),
                "RUNNER_MATRIX": json.dumps(runner_matrix),
                "FULL_MATRIX": json.dumps(full_matrix),
                "ACCEPTED_PROJECTS": "[]",
            },
            check=False,
        )
        assert result.returncode != 0
        assert "no supported runner upload succeeded" in (result.stderr + result.stdout).lower()
    finally:
        if github_output.exists():
            github_output.unlink()


def test_matrix_command_fails_without_github_output() -> None:
    result = _run("matrix", env={"BMT_CONFIG_ROOT": "remote/code", "GITHUB_OUTPUT": ""}, check=False)
    assert result.returncode != 0
    assert "GITHUB_OUTPUT" in result.stderr + result.stdout


def test_matrix_command_fails_with_invalid_config_root() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        result = _run(
            "matrix",
            env={"BMT_CONFIG_ROOT": "/nonexistent/path", "GITHUB_OUTPUT": str(github_output)},
            check=False,
        )
        assert result.returncode != 0
    finally:
        if github_output.exists():
            github_output.unlink()


def test_all_commands_are_registered() -> None:
    result = _run("nonexistent-command", check=False)
    assert result.returncode != 0
    expected_commands = [
        "matrix", "filter-supported-matrix", "parse-release-runners",
        "trigger", "upload-runner", "start-vm", "sync-vm-metadata", "wait-handshake",
    ]
    for cmd in expected_commands:
        assert cmd in result.stderr, f"Command '{cmd}' not listed in usage output"


def test_unknown_command_fails() -> None:
    result = _run("nonexistent-command", check=False)
    assert result.returncode != 0


def test_matrix_output_is_valid_json() -> None:
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
        github_output = Path(tmp.name)
    try:
        _run("matrix", env={"BMT_CONFIG_ROOT": "remote/code", "GITHUB_OUTPUT": str(github_output)})
        content = github_output.read_text()
        matrix_line = next(line for line in content.split("\n") if line.startswith("matrix="))
        parsed = json.loads(matrix_line.split("=", 1)[1])
        assert isinstance(parsed, dict)
        assert "include" in parsed
    finally:
        if github_output.exists():
            github_output.unlink()


def test_upload_runner_fails_without_required_env() -> None:
    result = _run("upload-runner", env={"GCS_BUCKET": "", "PROJECT": "", "PRESET": ""}, check=False)
    assert result.returncode != 0


def test_trigger_fails_with_invalid_matrix_json() -> None:
    result = _run(
        "trigger",
        env={
            "GCS_BUCKET": "test-bucket",
            "GITHUB_OUTPUT": "/tmp/test-out.txt",
            "FILTERED_MATRIX_JSON": "not-valid-json",
            "RUN_CONTEXT": "dev",
        },
        check=False,
    )
    assert result.returncode != 0

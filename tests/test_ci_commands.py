"""Integration tests for CI commands via bmt entry point subprocess."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from testutils import combined_output, decode_output_json, read_github_output


def _run(
    cmd: str,
    *,
    repo_root: Path,
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
        cwd=repo_root,
    )


def test_matrix_command_runs(repo_root: Path, gcp_code_root: Path, tmp_path: Path) -> None:
    config_root = gcp_code_root
    assert config_root.exists()
    assert (config_root / "bmt_projects.json").exists()

    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        repo_root=repo_root,
        env={"BMT_CONFIG_ROOT": str(gcp_code_root), "GITHUB_OUTPUT": str(github_output)},
    )
    assert result.returncode == 0
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")
    assert "include" in matrix
    assert len(matrix["include"]) > 0
    for entry in matrix["include"]:
        assert "project" in entry and "bmt_id" in entry
    assert "sk" in {e["project"] for e in matrix["include"]}


def test_matrix_command_with_filter(repo_root: Path, gcp_code_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        repo_root=repo_root,
        env={"BMT_CONFIG_ROOT": str(gcp_code_root), "BMT_PROJECTS": "sk", "GITHUB_OUTPUT": str(github_output)},
    )
    assert result.returncode == 0
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")
    assert {e["project"] for e in matrix["include"]} == {"sk"}


def test_matrix_command_with_all_filter(repo_root: Path, gcp_code_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        repo_root=repo_root,
        env={
            "BMT_CONFIG_ROOT": str(gcp_code_root),
            "BMT_PROJECTS": "all",
            "GITHUB_OUTPUT": str(github_output),
        },
    )
    assert result.returncode == 0
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")
    assert "sk" in {e["project"] for e in matrix["include"]}


def test_matrix_command_with_json_array_filter(repo_root: Path, gcp_code_root: Path, tmp_path: Path) -> None:
    """BMT_PROJECTS accepts a JSON array e.g. [\"sk\"] or [\"SK\"] (normalized to lowercase)."""
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        repo_root=repo_root,
        env={"BMT_CONFIG_ROOT": str(gcp_code_root), "BMT_PROJECTS": '["sk"]', "GITHUB_OUTPUT": str(github_output)},
    )
    assert result.returncode == 0
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")
    assert {e["project"] for e in matrix["include"]} == {"sk"}


def test_matrix_command_with_unsupported_filter_is_non_fatal(
    repo_root: Path, gcp_code_root: Path, tmp_path: Path
) -> None:
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        repo_root=repo_root,
        env={
            "BMT_CONFIG_ROOT": str(gcp_code_root),
            "BMT_PROJECTS": "does-not-exist",
            "GITHUB_OUTPUT": str(github_output),
        },
    )
    assert result.returncode == 0
    assert "No supported project+BMT rows found" in combined_output(result)
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")
    assert matrix["include"] == []


def test_filter_supported_matrix_success(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    runner_matrix = {"include": [{"project": "sk"}, {"project": "missing"}]}
    full_matrix = {"include": [{"project": "sk", "bmt_id": "sk-bmt"}]}
    result = _run(
        "filter-supported-matrix",
        repo_root=repo_root,
        env={
            "GITHUB_OUTPUT": str(github_output),
            "RUNNER_MATRIX": json.dumps(runner_matrix),
            "FULL_MATRIX": json.dumps(full_matrix),
            "ACCEPTED_PROJECTS": json.dumps(["sk"]),
        },
    )
    assert result.returncode == 0
    outputs = read_github_output(github_output)
    matrix: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")
    assert outputs.get("has_legs") == "true"
    assert matrix["include"] == [{"project": "sk", "bmt_id": "sk-bmt"}]


def test_filter_supported_matrix_fails_when_no_uploaded_supported_projects(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    runner_matrix = {"include": [{"project": "sk"}]}
    full_matrix = {"include": [{"project": "sk", "bmt_id": "sk-bmt"}]}
    result = _run(
        "filter-supported-matrix",
        repo_root=repo_root,
        env={
            "GITHUB_OUTPUT": str(github_output),
            "RUNNER_MATRIX": json.dumps(runner_matrix),
            "FULL_MATRIX": json.dumps(full_matrix),
            "ACCEPTED_PROJECTS": "[]",
        },
        check=False,
    )
    assert result.returncode != 0
    assert "no supported runner upload succeeded" in combined_output(result).lower()


def test_matrix_command_fails_without_github_output(repo_root: Path, gcp_code_root: Path) -> None:
    result = _run(
        "matrix",
        repo_root=repo_root,
        env={"BMT_CONFIG_ROOT": str(gcp_code_root), "GITHUB_OUTPUT": ""},
        check=False,
    )
    assert result.returncode != 0
    assert "GITHUB_OUTPUT" in combined_output(result)


def test_matrix_command_fails_with_invalid_config_root(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        repo_root=repo_root,
        env={"BMT_CONFIG_ROOT": "/nonexistent/path", "GITHUB_OUTPUT": str(github_output)},
        check=False,
    )
    assert result.returncode != 0


def test_all_commands_are_registered(repo_root: Path) -> None:
    result = _run("nonexistent-command", repo_root=repo_root, check=False)
    assert result.returncode != 0
    expected_commands = [
        "matrix",
        "filter-supported-matrix",
        "parse-release-runners",
        "trigger",
        "upload-runner",
        "start-vm",
        "sync-vm-metadata",
        "wait-handshake",
    ]
    for cmd in expected_commands:
        assert cmd in result.stderr, f"Command '{cmd}' not listed in usage output"


def test_unknown_command_fails(repo_root: Path) -> None:
    result = _run("nonexistent-command", repo_root=repo_root, check=False)
    assert result.returncode != 0


def test_matrix_output_is_valid_json(repo_root: Path, gcp_code_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    _run(
        "matrix",
        repo_root=repo_root,
        env={"BMT_CONFIG_ROOT": str(gcp_code_root), "GITHUB_OUTPUT": str(github_output)},
    )
    outputs = read_github_output(github_output)
    parsed: dict[str, list[dict[str, str]]] = decode_output_json(outputs, "matrix")
    assert isinstance(parsed, dict)
    assert "include" in parsed


def test_upload_runner_fails_without_required_env(repo_root: Path) -> None:
    result = _run(
        "upload-runner",
        repo_root=repo_root,
        env={"GCS_BUCKET": "", "PROJECT": "", "PRESET": ""},
        check=False,
    )
    assert result.returncode != 0


def test_trigger_fails_with_invalid_matrix_json(repo_root: Path, tmp_path: Path) -> None:
    result = _run(
        "trigger",
        repo_root=repo_root,
        env={
            "GCS_BUCKET": "test-bucket",
            "GITHUB_OUTPUT": str(tmp_path / "test-out.txt"),
            "FILTERED_MATRIX_JSON": "not-valid-json",
            "RUN_CONTEXT": "dev",
        },
        check=False,
    )
    assert result.returncode != 0

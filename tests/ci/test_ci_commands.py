"""Integration tests for CI commands via bmt entry point subprocess."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests._support.testutils import (
    assert_github_matrix_include_shape,
    combined_output,
    decode_output_json,
    read_github_output,
)

pytestmark = pytest.mark.integration


def _run(
    *cmd: str,
    repo_root: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["uv", "run", "kardome-bmt", *cmd],
        check=check,
        capture_output=True,
        text=True,
        env=full_env,
        cwd=repo_root,
    )


def test_matrix_command_runs(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        "build",
        repo_root=repo_root,
        env={"GITHUB_OUTPUT": str(github_output)},
    )
    assert result.returncode == 0
    outputs = read_github_output(github_output)
    matrix = decode_output_json(outputs, "matrix")
    assert_github_matrix_include_shape(matrix)
    assert "sk" in {e["project"] for e in matrix["include"]}


def test_matrix_command_ignores_unrelated_env(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        "build",
        repo_root=repo_root,
        env={"UNRELATED_FILTER": "sk", "GITHUB_OUTPUT": str(github_output)},
    )
    assert result.returncode == 0
    outputs = read_github_output(github_output)
    matrix = decode_output_json(outputs, "matrix")
    assert "sk" in {e["project"] for e in matrix["include"]}


def test_filter_supported_matrix_success(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    runner_matrix = {"include": [{"project": "sk"}, {"project": "missing"}]}
    full_matrix = {"include": [{"project": "sk", "bmt_id": "sk-bmt"}]}
    result = _run(
        "matrix",
        "filter-supported",
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
    matrix = decode_output_json(outputs, "matrix")
    assert outputs.get("has_legs") == "true"
    assert matrix["include"] == [{"project": "sk", "bmt_id": "sk-bmt"}]


def test_filter_supported_matrix_fails_when_no_uploaded_supported_projects(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    runner_matrix = {"include": [{"project": "sk"}]}
    full_matrix = {"include": [{"project": "sk", "bmt_id": "sk-bmt"}]}
    result = _run(
        "matrix",
        "filter-supported",
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


def test_matrix_command_fails_without_github_output(repo_root: Path) -> None:
    result = _run(
        "matrix",
        "build",
        repo_root=repo_root,
        env={"GITHUB_OUTPUT": ""},
        check=False,
    )
    assert result.returncode != 0
    assert "GITHUB_OUTPUT" in combined_output(result)


def test_matrix_command_fails_with_invalid_presets_file(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    result = _run(
        "matrix",
        "build",
        repo_root=repo_root,
        env={"BMT_PRESETS_FILE": "/nonexistent/path", "GITHUB_OUTPUT": str(github_output)},
        check=False,
    )
    assert result.returncode != 0


def test_help_lists_command_groups(repo_root: Path) -> None:
    result = _run("--help", repo_root=repo_root)
    assert result.returncode == 0
    out = result.stdout + result.stderr
    for name in ("matrix", "runner", "handoff", "dispatch", "preset", "meta"):
        assert name in out, f"Expected Typer group {name!r} in help"


def test_unknown_command_fails(repo_root: Path) -> None:
    result = _run("not-a-registered-group", repo_root=repo_root, check=False)
    assert result.returncode != 0


def test_matrix_output_is_valid_json(repo_root: Path, tmp_path: Path) -> None:
    github_output = tmp_path / "github_output.txt"
    _run(
        "matrix",
        "build",
        repo_root=repo_root,
        env={"GITHUB_OUTPUT": str(github_output)},
    )
    outputs = read_github_output(github_output)
    parsed = decode_output_json(outputs, "matrix")
    assert_github_matrix_include_shape(parsed)


def test_upload_runner_fails_without_required_env(repo_root: Path) -> None:
    result = _run(
        "runner",
        "upload",
        repo_root=repo_root,
        env={"GCS_BUCKET": "", "PROJECT": "", "PRESET": ""},
        check=False,
    )
    assert result.returncode != 0

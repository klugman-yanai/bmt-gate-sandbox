"""Contract tests for GitHub Actions matrix / GITHUB_OUTPUT decoding.

These mirror the assertions used by integration tests in ``test_ci_commands`` without
``xfail`` or subprocess-parsed pytest summaries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.testutils import (
    assert_github_matrix_include_shape,
    assert_matrix_projects_subset,
    decode_output_json,
    read_github_output,
)

pytestmark = pytest.mark.contract


def test_matrix_contract_rejects_missing_include_key(tmp_path: Path) -> None:
    github_output = tmp_path / "missing-include.txt"
    github_output.write_text('matrix={"wrong_key": []}', encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix = decode_output_json(outputs, "matrix")
    with pytest.raises(AssertionError, match="include"):
        assert_github_matrix_include_shape(matrix)


def test_matrix_contract_rejects_empty_include(tmp_path: Path) -> None:
    github_output = tmp_path / "empty-matrix.txt"
    github_output.write_text('matrix={"include": []}', encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix = decode_output_json(outputs, "matrix")
    with pytest.raises(AssertionError, match="empty"):
        assert_github_matrix_include_shape(matrix)


def test_matrix_contract_rejects_missing_project_field(tmp_path: Path) -> None:
    github_output = tmp_path / "missing-project.txt"
    github_output.write_text('matrix={"include": [{"bmt_id": "test"}]}', encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix = decode_output_json(outputs, "matrix")
    with pytest.raises(AssertionError, match="project"):
        assert_github_matrix_include_shape(matrix)


def test_matrix_contract_rejects_filter_leakage(tmp_path: Path) -> None:
    github_output = tmp_path / "filter-leak.txt"
    github_output.write_text(
        'matrix={"include": [{"project": "sk", "bmt_id": "test1"}, {"project": "continental", "bmt_id": "test2"}]}',
        encoding="utf-8",
    )
    outputs = read_github_output(github_output)
    matrix = decode_output_json(outputs, "matrix")
    with pytest.raises(AssertionError, match="Filter leaked"):
        assert_matrix_projects_subset(matrix, {"sk"})


def test_json_decode_rejects_invalid_matrix_payload(tmp_path: Path) -> None:
    github_output = tmp_path / "invalid-json.txt"
    github_output.write_text("matrix={invalid json here", encoding="utf-8")
    outputs = read_github_output(github_output)
    matrix_json = outputs["matrix"]
    with pytest.raises(json.JSONDecodeError):
        json.loads(matrix_json)

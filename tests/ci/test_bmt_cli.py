"""Typer CLI smoke tests (no subprocess)."""

from __future__ import annotations

import pytest
from ci.driver import app
from typer.testing import CliRunner

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_root_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "matrix" in result.stdout


def test_matrix_build_help() -> None:
    result = runner.invoke(app, ["matrix", "build", "--help"])
    assert result.exit_code == 0
    assert "GITHUB_OUTPUT" in result.stdout or "Emit BMT matrix" in result.stdout

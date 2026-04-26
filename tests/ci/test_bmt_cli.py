"""Typer CLI smoke tests (no subprocess)."""

from __future__ import annotations

from typer.testing import CliRunner

from ci.kardome_bmt.driver import app

runner = CliRunner()


def test_root_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "matrix" in result.stdout


def test_matrix_build_help() -> None:
    result = runner.invoke(app, ["matrix", "build", "--help"])
    assert result.exit_code == 0
    assert "GITHUB_OUTPUT" in result.stdout or "Emit BMT matrix" in result.stdout

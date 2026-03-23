"""Integration tests for `tools workflow` commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tools.__main__ import app, register_subcommands

pytestmark = pytest.mark.integration

runner = CliRunner()


def _tools_app():
    register_subcommands(app)
    return app


def test_workflow_help_lists_subcommands() -> None:
    result = runner.invoke(_tools_app(), ["workflow", "--help"])
    assert result.exit_code == 0
    assert "overview" in result.stdout
    assert "status" in result.stdout


def test_workflow_overview_exits_zero() -> None:
    result = runner.invoke(_tools_app(), ["workflow", "overview"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "onboard" in out or "stage" in out
    assert "just add" in out or "add <project>" in out
    assert "test-local" in out
    assert "publish" in out
    assert "sync-to-bucket" in out


def test_workflow_status_exits_zero() -> None:
    result = runner.invoke(_tools_app(), ["workflow", "status"])
    assert result.exit_code == 0
    assert "repo status" in result.stdout.lower()
    assert ".venv" in result.stdout.lower() or "venv" in result.stdout.lower()

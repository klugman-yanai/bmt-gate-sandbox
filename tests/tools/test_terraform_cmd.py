"""Tests for tools.cli.terraform_cmd."""
from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from tools.cli.terraform_cmd import app

runner = CliRunner()


def test_apply_calls_preflight_then_apply():
    """Default 'apply' runs preflight then apply."""
    calls = []

    def fake_run(module: str, **kw: object) -> int:
        calls.append(module)
        return 0

    with patch("tools.cli.terraform_cmd._run_tool", side_effect=fake_run):
        result = runner.invoke(app, ["apply"])
        assert result.exit_code == 0
        assert "terraform_preflight" in str(calls[0])
        assert "terraform_apply" in str(calls[1])


def test_apply_verbose_passes_flag():
    """--verbose passes through to underlying tools."""
    with patch("tools.cli.terraform_cmd._run_tool", return_value=0) as mock:
        result = runner.invoke(app, ["apply", "--verbose"])
        assert result.exit_code == 0
        assert any(
            (call[1] or {}).get("verbose") for call in mock.call_args_list
        ), "Expected at least one call with verbose=True"


def test_import_topics_subcommand():
    """import-topics runs the import tool."""
    with patch("tools.cli.terraform_cmd._run_tool", return_value=0) as mock:
        result = runner.invoke(app, ["import-topics"])
        assert result.exit_code == 0
        assert mock.called

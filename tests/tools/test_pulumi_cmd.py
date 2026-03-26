"""Tests for tools.cli.pulumi_cmd (Pulumi apply/preflight)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tools.cli.pulumi_cmd import app

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_apply_calls_preflight_then_apply():
    """Default 'apply' runs preflight then apply."""
    calls = []

    def fake_run(module: str, **kw: object) -> int:
        calls.append(module)
        return 0

    with patch("tools.cli.pulumi_cmd._run_tool", side_effect=fake_run):
        result = runner.invoke(app, ["apply"])
        assert result.exit_code == 0
        assert "pulumi_preflight" in str(calls[0])
        assert "pulumi_apply" in str(calls[1])


def test_apply_verbose_passes_flag():
    """--verbose passes through to underlying tools."""
    with patch("tools.cli.pulumi_cmd._run_tool", return_value=0) as mock:
        result = runner.invoke(app, ["apply", "--verbose"])
        assert result.exit_code == 0
        assert any((call[1] or {}).get("verbose") for call in mock.call_args_list), (
            "Expected at least one call with verbose=True"
        )

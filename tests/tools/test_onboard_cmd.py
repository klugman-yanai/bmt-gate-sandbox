"""Tests for ``tools onboard`` (post-bootstrap Rich summary)."""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from tools.__main__ import app, register_subcommands

pytestmark = pytest.mark.integration

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(s: str) -> str:
    return _ANSI.sub("", s)


def _tools_app():
    register_subcommands(app)
    return app


def test_onboard_help_lists_options() -> None:
    result = runner.invoke(_tools_app(), ["onboard", "--help"])
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "onboard" in out
    assert "--dry-run" in out
    assert "--prek-state" in out


def test_onboard_prek_state_without_dry_run_fails() -> None:
    result = runner.invoke(_tools_app(), ["onboard", "--prek-state", "would-install"])
    assert result.exit_code == 2
    combined = _plain(result.stdout + result.stderr).lower()
    assert "dry-run" in combined


def test_onboard_prek_state_invalid_value_fails() -> None:
    result = runner.invoke(
        _tools_app(),
        ["onboard", "--dry-run", "--prek-state", "not-a-valid-state"],
    )
    assert result.exit_code == 2
    assert "must be one of" in _plain(result.stdout + result.stderr).lower()


def test_onboard_dry_run_exits_zero() -> None:
    """Smoke: dry-run path does not raise (Rich may be disabled in CI)."""
    result = runner.invoke(_tools_app(), ["onboard", "--dry-run", "--prek-state", "would-install"])
    assert result.exit_code == 0

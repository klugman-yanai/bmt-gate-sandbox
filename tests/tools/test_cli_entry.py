"""Smoke tests for the unified tools CLI entry point."""

from __future__ import annotations

import subprocess
import sys

import pytest
from typer.testing import CliRunner

from tools.__main__ import app, register_subcommands

pytestmark = pytest.mark.integration

runner = CliRunner()


def _tools_app():
    register_subcommands(app)
    return app


def test_tools_help() -> None:
    """tools --help exits 0 and shows command groups."""
    result = runner.invoke(_tools_app(), ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    for group in ("bucket", "pulumi", "repo", "build", "bmt"):
        assert group in out


def test_bucket_help() -> None:
    """bucket --help shows deploy, preflight, clean-bloat, and project sync helpers."""
    result = runner.invoke(_tools_app(), ["bucket", "--help"])
    assert result.exit_code == 0
    assert "deploy" in result.stdout
    assert "project-sync" in result.stdout


def test_build_help() -> None:
    """build --help shows image and packer-validate."""
    result = runner.invoke(_tools_app(), ["build", "--help"])
    assert result.exit_code == 0
    assert "image" in result.stdout
    assert "packer-validate" in result.stdout


def test_pulumi_help() -> None:
    """pulumi --help shows apply and preflight."""
    result = runner.invoke(_tools_app(), ["pulumi", "--help"])
    assert result.exit_code == 0
    assert "apply" in result.stdout
    assert "preflight" in result.stdout


def test_bmt_help() -> None:
    """bmt --help shows the stage scaffold and publish commands."""
    result = runner.invoke(_tools_app(), ["bmt", "--help"])
    assert result.exit_code == 0
    assert "add-project" in result.stdout
    assert "add-bmt" in result.stdout
    assert "publish-bmt" in result.stdout


def test_python_m_tools_help_entrypoint_smoke() -> None:
    """One subprocess smoke: ``python -m tools`` wiring (distinct from Typer in-process)."""
    result = subprocess.run(
        [sys.executable, "-m", "tools", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "bucket" in result.stdout

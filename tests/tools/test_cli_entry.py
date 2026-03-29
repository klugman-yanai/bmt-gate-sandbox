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
    for group in ("bucket", "pulumi", "repo", "build", "bmt", "workspace", "workflow", "add", "publish"):
        assert group in out
    assert "release-check" in out
    assert "set-lifecycle" in out
    assert "doctor" in out
    assert "typecheck" in out


def test_bucket_help() -> None:
    """bucket --help shows deploy, preflight, clean-bloat, and project sync helpers."""
    result = runner.invoke(_tools_app(), ["bucket", "--help"])
    assert result.exit_code == 0
    out = result.stdout
    assert "deploy" in out
    assert "project-sync" in out
    assert "upload-wav" in out


def test_build_help() -> None:
    """build --help shows orchestrator-image, VM image dispatch, and packer-validate."""
    result = runner.invoke(_tools_app(), ["build", "--help"])
    assert result.exit_code == 0
    out = result.stdout
    assert "orchestrator-image" in out
    assert "image" in out
    assert "packer-validate" in out


def test_workspace_help() -> None:
    """workspace --help lists pulumi, validate, preflight, deploy, e2e."""
    result = runner.invoke(_tools_app(), ["workspace", "--help"])
    assert result.exit_code == 0
    out = result.stdout
    for name in ("pulumi", "validate", "preflight", "deploy", "e2e"):
        assert name in out


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
    assert "stage" in result.stdout
    assert "ops" in result.stdout


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
    assert "workflow" in result.stdout

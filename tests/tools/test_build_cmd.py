"""Tests for tools.cli.build_cmd (image build orchestration)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from tools.cli.build_cmd import app

runner = CliRunner()


def test_image_packer_validate_called():
    """Packer validate runs before dispatch."""
    with (
        patch("tools.cli.build_cmd._run_packer_validate", return_value=0) as mock_pv,
        patch("tools.cli.build_cmd._dispatch_and_wait", return_value=0),
    ):
        result = runner.invoke(app, ["image"])
        assert mock_pv.called


def test_image_skip_image_runs_terraform_only():
    """--skip-image skips image build and runs terraform."""
    with (
        patch("tools.cli.build_cmd._run_terraform", return_value=0) as mock_tf,
        patch("tools.cli.build_cmd._run_packer_validate") as mock_pv,
    ):
        result = runner.invoke(app, ["image", "--skip-image"])
        assert not mock_pv.called
        assert mock_tf.called


def test_image_no_wait_dispatches_only():
    """--no-wait dispatches without waiting."""
    with (
        patch("tools.cli.build_cmd._run_packer_validate", return_value=0),
        patch("tools.cli.build_cmd._dispatch_workflow") as mock_dispatch,
    ):
        result = runner.invoke(app, ["image", "--no-wait"])
        assert mock_dispatch.called


def test_packer_validate_command():
    """packer-validate runs packer validate with dry-run vars."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["packer-validate"])
        assert result.exit_code == 0
        cmd = mock_run.call_args[0][0]
        assert "packer" in cmd[0]
        assert "validate" in cmd

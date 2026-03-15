"""Smoke tests for the unified tools CLI entry point."""
from __future__ import annotations

import subprocess
import sys


def test_tools_help():
    """tools --help exits 0 and shows command groups."""
    result = subprocess.run(
        [sys.executable, "-m", "tools", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for group in ("bucket", "terraform", "repo", "build", "bmt"):
        assert group in result.stdout


def test_bucket_help():
    """bucket --help shows deploy, preflight, clean-bloat."""
    result = subprocess.run(
        [sys.executable, "-m", "tools", "bucket", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "deploy" in result.stdout


def test_build_help():
    """build --help shows image and packer-validate."""
    result = subprocess.run(
        [sys.executable, "-m", "tools", "build", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "image" in result.stdout
    assert "packer-validate" in result.stdout


def test_terraform_help():
    """terraform --help shows apply and import-topics."""
    result = subprocess.run(
        [sys.executable, "-m", "tools", "terraform", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "apply" in result.stdout
    assert "import-topics" in result.stdout

"""Shared pytest path fixtures.

These are re-exported via tests/conftest.py so all tests can use them without
an explicit import. New tests can also import directly from this module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]  # tests/support/fixtures/paths.py → repo root


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _ROOT


@pytest.fixture(scope="session")
def gcp_code_root(repo_root: Path) -> Path:
    """VM deployable code root (gcp/image mirrors bucket code/)."""
    path = repo_root / "gcp" / "image"
    assert path.exists(), f"Expected gcp image root to exist: {path}"
    return path


@pytest.fixture(scope="session")
def github_bmt_root(repo_root: Path) -> Path:
    path = repo_root / ".github" / "bmt"
    assert path.exists(), f"Expected .github/bmt root to exist: {path}"
    return path


@pytest.fixture(scope="session")
def repo_stage_root(repo_root: Path) -> Path:
    path = repo_root / "gcp" / "stage"
    assert path.exists(), f"Expected gcp/stage to exist: {path}"
    return path

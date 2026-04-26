"""Shared pytest path fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _ROOT


@pytest.fixture(scope="session")
def runtime_root(repo_root: Path) -> Path:
    """Cloud Run execution runtime package root."""
    path = repo_root / "runtime"
    assert path.exists(), f"Expected runtime root to exist: {path}"
    return path


# Keep old name as alias so tests that use gcp_code_root don't break until updated.
@pytest.fixture(scope="session")
def gcp_code_root(runtime_root: Path) -> Path:
    return runtime_root


@pytest.fixture(scope="session")
def ci_root(repo_root: Path) -> Path:
    path = repo_root / "ci"
    assert path.exists(), f"Expected ci root to exist: {path}"
    return path


# Keep old name as alias.
@pytest.fixture(scope="session")
def github_bmt_root(ci_root: Path) -> Path:
    return ci_root


@pytest.fixture(scope="session")
def plugins_root(repo_root: Path) -> Path:
    path = repo_root / "plugins"
    assert path.exists(), f"Expected plugins root to exist: {path}"
    return path


# Keep old name as alias.
@pytest.fixture(scope="session")
def repo_stage_root(plugins_root: Path) -> Path:
    return plugins_root

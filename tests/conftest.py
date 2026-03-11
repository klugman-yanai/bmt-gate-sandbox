"""Shared pytest path/bootstrap config and canonical path fixtures."""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_EXTRA_PATHS = [
    _ROOT / ".github" / "bmt",
    _ROOT / "tools",
    _ROOT,
    _ROOT / "gcp",
    _ROOT / "gcp" / "code",
    _ROOT / "gcp" / "code" / "lib",
    _ROOT / "gcp" / "code" / "sk",
]
for path in _EXTRA_PATHS:
    sys.path.insert(0, str(path))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _ROOT


@pytest.fixture(scope="session")
def gcp_code_root(repo_root: Path) -> Path:
    path = repo_root / "gcp" / "code"
    assert path.exists(), f"Expected gcp code root to exist: {path}"
    return path


@pytest.fixture(scope="session")
def github_bmt_root(repo_root: Path) -> Path:
    path = repo_root / ".github" / "bmt"
    assert path.exists(), f"Expected .github/bmt root to exist: {path}"
    return path


@pytest.fixture(autouse=True)
def _stable_repo_cwd(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    # Keep relative-path behavior deterministic regardless of where pytest is invoked.
    monkeypatch.chdir(repo_root)

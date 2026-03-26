"""Root conftest — session-scoped fixtures and CWD stability.

Path fixtures (repo_root, gcp_code_root, github_bmt_root, repo_stage_root) live in
tests/support/fixtures/paths.py and are re-exported here so all tests can use them
without an explicit import.

Test-layer markers (unit, integration, contract, bmt_plugin_load) are applied per module
via ``pytestmark`` or per-test decorators; see tests/README.md.
"""

from pathlib import Path

import pytest

from tests.support.fixtures.paths import gcp_code_root, github_bmt_root, repo_root, repo_stage_root, stage_paths

__all__ = ["gcp_code_root", "github_bmt_root", "repo_root", "repo_stage_root", "stage_paths"]

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _stable_repo_cwd(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    # Keep relative-path behavior deterministic regardless of where pytest is invoked.
    monkeypatch.chdir(repo_root)

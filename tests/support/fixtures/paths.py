"""Shared pytest path fixtures.

These are re-exported via tests/conftest.py so all tests can use them without
an explicit import. New tests can also import directly from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]  # tests/support/fixtures/paths.py → repo root


# ---------------------------------------------------------------------------
# StagePaths — mirrors the GCS bucket / gcp/stage layout for tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StagePaths:
    """Path builder that mirrors the ``gcp/stage`` / GCS bucket layout.

    Centralises path-segment construction so tests never hard-code strings
    like ``"projects" / project / "bmts" / <benchmark> / "bmt.json"`` inline (folder = manifest ``bmt_slug``).
    """

    root: Path

    # -- projects ----------------------------------------------------------

    def project(self, name: str) -> Path:
        return self.root / "projects" / name

    def bmt_manifest(self, project: str, bmt_slug: str) -> Path:
        return self.project(project) / "bmts" / bmt_slug / "bmt.json"

    def results(self, project: str, bmt_slug: str) -> Path:
        return self.project(project) / "results" / bmt_slug

    def current_json(self, project: str, bmt_slug: str) -> Path:
        return self.results(project, bmt_slug) / "current.json"

    def snapshot(self, project: str, run_id: str) -> Path:
        return self.project(project) / "results" / run_id

    def inputs(self, project: str, bmt_slug: str) -> Path:
        return self.project(project) / "inputs" / bmt_slug

    def plugin_workspace(self, project: str, name: str) -> Path:
        return self.project(project) / "plugin_workspaces" / name

    # -- triggers ----------------------------------------------------------

    def trigger_plan(self, workflow_id: str) -> Path:
        return self.root / "triggers" / "plans" / f"{workflow_id}.json"

    def trigger_summary(self, workflow_id: str, project: str, bmt_id: str) -> Path:
        return self.root / "triggers" / "summaries" / workflow_id / f"{project}-{bmt_id}.json"

    def trigger_reporting(self, workflow_id: str) -> Path:
        return self.root / "triggers" / "reporting" / f"{workflow_id}.json"

    def trigger_progress(self, workflow_id: str) -> Path:
        return self.root / "triggers" / "progress" / workflow_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


@pytest.fixture
def stage_paths(tmp_path: Path) -> StagePaths:
    """Ephemeral ``StagePaths`` rooted in ``tmp_path / "gcp" / "stage"``."""
    return StagePaths(tmp_path / "gcp" / "stage")

"""Unit tests for contributor workflow step order and repo hints."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.workflow.guide import repo_workflow_hints, workflow_steps_ordered


def test_workflow_order_matches_onboarding_story() -> None:
    steps = workflow_steps_ordered()
    keys = [s.key for s in steps]
    assert keys == [
        "onboard",
        "contributor_add",
        "edit_scaffold",
        "test_local",
        "publish_plugin",
        "workspace_deploy",
        "test",
    ]


def test_repo_hints_fresh_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    h = repo_workflow_hints(repo_root=tmp_path)
    assert h.has_venv is False
    assert h.stage_project_names == []


def test_repo_hints_lists_stage_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    projs = tmp_path / "benchmarks" / "projects"
    projs.mkdir(parents=True)
    (projs / "alpha").mkdir()
    (projs / "beta").mkdir()
    h = repo_workflow_hints(repo_root=tmp_path)
    assert h.stage_project_names == ["alpha", "beta"]

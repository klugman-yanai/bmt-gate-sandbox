"""Unit tests for ``backend.runtime.stage_paths``."""

from __future__ import annotations

from pathlib import Path

import pytest
from backend.runtime.stage_paths import (
    iter_bmt_manifest_paths,
    iter_bmt_manifest_paths_for_project,
    published_dir_for_new_publish,
    resolve_bmt_manifest_path,
    resolve_plugin_workspace_dir,
    resolve_published_plugin_dir,
)

pytestmark = pytest.mark.unit


def test_iter_bmt_manifest_paths_dedupes_v1_v2_same_repo(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    acme = projects_root / "acme"
    (acme / "bmts" / "b1").mkdir(parents=True)
    (acme / "bmts" / "b1" / "bmt.json").write_text("{}", encoding="utf-8")
    (acme / "benchmarks" / "b2").mkdir(parents=True)
    (acme / "benchmarks" / "b2" / "bmt.json").write_text("{}", encoding="utf-8")
    paths = iter_bmt_manifest_paths(projects_root=projects_root)
    assert len(paths) == 2


def test_resolve_workspace_v2_over_v1(tmp_path: Path) -> None:
    stage = tmp_path
    pr = stage / "projects" / "p"
    (pr / "plugins" / "def" / "workspace").mkdir(parents=True)
    (pr / "plugin_workspaces" / "def").mkdir(parents=True)
    assert resolve_plugin_workspace_dir(stage, "p", "def") == pr / "plugins" / "def" / "workspace"


def test_resolve_workspace_v1_fallback(tmp_path: Path) -> None:
    stage = tmp_path
    pr = stage / "projects" / "p"
    (pr / "plugin_workspaces" / "def").mkdir(parents=True)
    assert resolve_plugin_workspace_dir(stage, "p", "def") == pr / "plugin_workspaces" / "def"


def test_resolve_workspace_flat_project_root(tmp_path: Path) -> None:
    """``projects/<id>/plugin.json`` at project root → workspace dir is the project directory."""
    stage = tmp_path
    pr = stage / "projects" / "sk"
    pr.mkdir(parents=True)
    (pr / "plugin.json").write_text("{}", encoding="utf-8")
    assert resolve_plugin_workspace_dir(stage, "sk", "main") == pr


def test_resolve_published_v2_over_v1(tmp_path: Path) -> None:
    stage = tmp_path
    pr = stage / "projects" / "p"
    dig = "sha256-abc"
    (pr / "plugins" / "def" / "releases" / dig).mkdir(parents=True)
    (pr / "plugins" / "def" / dig).mkdir(parents=True)
    assert resolve_published_plugin_dir(stage, "p", "def", dig) == pr / "plugins" / "def" / "releases" / dig


def test_published_dir_for_new_publish_v2_workspace(tmp_path: Path) -> None:
    stage = tmp_path
    pr = stage / "projects" / "p"
    (pr / "plugins" / "def" / "workspace").mkdir(parents=True)
    out = published_dir_for_new_publish(stage, "p", "def", "deadbeef")
    assert out == pr / "plugins" / "def" / "releases" / "sha256-deadbeef"


def test_published_dir_for_new_publish_v1_workspace(tmp_path: Path) -> None:
    stage = tmp_path
    pr = stage / "projects" / "p"
    (pr / "plugin_workspaces" / "def").mkdir(parents=True)
    out = published_dir_for_new_publish(stage, "p", "def", "deadbeef")
    assert out == pr / "plugins" / "def" / "sha256-deadbeef"


def test_resolve_bmt_manifest_benchmarks_first(tmp_path: Path) -> None:
    stage = tmp_path
    pr = stage / "projects" / "p"
    (pr / "benchmarks" / "x").mkdir(parents=True)
    (pr / "benchmarks" / "x" / "bmt.json").write_text("{}", encoding="utf-8")
    (pr / "bmts" / "x").mkdir(parents=True)
    (pr / "bmts" / "x" / "bmt.json").write_text("{}", encoding="utf-8")
    p = resolve_bmt_manifest_path(stage, "p", "x")
    assert p == pr / "benchmarks" / "x" / "bmt.json"


def test_iter_bmt_manifest_paths_for_project_prefers_one_per_slug(tmp_path: Path) -> None:
    stage = tmp_path
    pr = stage / "projects" / "p"
    (pr / "benchmarks" / "x").mkdir(parents=True)
    (pr / "benchmarks" / "x" / "bmt.json").write_text('{"a":1}', encoding="utf-8")
    paths = iter_bmt_manifest_paths_for_project(stage_root=stage, project="p")
    assert len(paths) == 1

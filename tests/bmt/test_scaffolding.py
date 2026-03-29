from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.bmt.scaffold import add_bmt, add_project

pytestmark = pytest.mark.unit


def test_add_project_creates_stage_scaffold(tmp_path: Path) -> None:
    stage_root = tmp_path / "benchmarks"

    rc = add_project("acme", stage_root=stage_root, dry_run=False)

    assert rc == 0
    project_root = stage_root / "projects" / "acme"
    assert (project_root / "project.json").is_file()
    assert (project_root / "README.md").is_file()
    assert (project_root / "plugin.json").is_file()
    assert (project_root / "src" / "acme_plugin" / "plugin.py").is_file()
    assert (project_root / "bmts" / "example" / "bmt.json").is_file()

    project_manifest = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert project_manifest["project"] == "acme"


def test_add_bmt_creates_disabled_manifest(tmp_path: Path) -> None:
    stage_root = tmp_path / "benchmarks"
    add_project("acme", stage_root=stage_root, dry_run=False)

    rc = add_bmt("acme", "wake_word_quality", stage_root=stage_root, plugin="main")

    assert rc == 0
    manifest_path = stage_root / "projects" / "acme" / "bmts" / "wake_word_quality" / "bmt.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["enabled"] is False
    assert manifest["plugin_ref"] == "workspace:main"
    assert manifest["bmt_slug"] == "wake_word_quality"

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.bmt.publisher import publish_bmt
from tools.bmt.scaffold import add_bmt, add_project


def test_publish_bmt_creates_immutable_bundle_updates_manifest_and_syncs(tmp_path: Path, monkeypatch) -> None:
    stage_root = tmp_path / "gcp" / "stage"
    add_project("acme", stage_root=stage_root, dry_run=False)
    add_bmt("acme", "wake_word_quality", stage_root=stage_root, plugin="default")

    plugin_file = (
        stage_root / "projects" / "acme" / "plugin_workspaces" / "default" / "src" / "acme_plugin" / "plugin.py"
    )
    plugin_file.write_text(
        plugin_file.read_text(encoding="utf-8") + "\nPLUGIN_SENTINEL = 'published'\n",
        encoding="utf-8",
    )

    synced: list[str] = []

    def _fake_sync(*, bucket: str, project: str, stage_root: Path | None = None) -> int:
        assert stage_root == stage_root_arg
        assert bucket == "demo-bucket"
        synced.append(project)
        return 0

    stage_root_arg = stage_root
    monkeypatch.setenv("GCS_BUCKET", "demo-bucket")
    monkeypatch.setattr("tools.bmt.publisher.sync_project", _fake_sync)

    result = publish_bmt(stage_root=stage_root, project="acme", bmt_slug="wake_word_quality")

    assert result.plugin_ref.startswith("published:default:sha256-")
    assert result.published_dir.is_dir()
    published_manifest = json.loads((result.published_dir / "plugin.json").read_text(encoding="utf-8"))
    assert published_manifest["entrypoint"] == "acme_plugin:AcmePlugin"
    bmt_manifest = json.loads(
        (stage_root / "projects" / "acme" / "bmts" / "wake_word_quality" / "bmt.json").read_text(encoding="utf-8")
    )
    assert bmt_manifest["plugin_ref"] == result.plugin_ref
    assert synced == ["acme"]


def test_publish_bmt_can_skip_sync(tmp_path: Path, monkeypatch) -> None:
    stage_root = tmp_path / "gcp" / "stage"
    add_project("acme", stage_root=stage_root, dry_run=False)
    add_bmt("acme", "wake_word_quality", stage_root=stage_root, plugin="default")

    called = False

    def _fake_sync(**_: object) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr("tools.bmt.publisher.sync_project", _fake_sync)

    publish_bmt(stage_root=stage_root, project="acme", bmt_slug="wake_word_quality", sync=False)

    assert called is False


def test_publish_bmt_fails_before_sync_when_workspace_plugin_is_invalid(tmp_path: Path, monkeypatch) -> None:
    stage_root = tmp_path / "gcp" / "stage"
    add_project("acme", stage_root=stage_root, dry_run=False)
    add_bmt("acme", "wake_word_quality", stage_root=stage_root, plugin="default")

    plugin_file = (
        stage_root / "projects" / "acme" / "plugin_workspaces" / "default" / "src" / "acme_plugin" / "plugin.py"
    )
    plugin_file.write_text("not valid python(", encoding="utf-8")

    called = False

    def _fake_sync(**_: object) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr("tools.bmt.publisher.sync_project", _fake_sync)

    with pytest.raises(Exception):
        publish_bmt(stage_root=stage_root, project="acme", bmt_slug="wake_word_quality")

    manifest = json.loads(
        (stage_root / "projects" / "acme" / "bmts" / "wake_word_quality" / "bmt.json").read_text(encoding="utf-8")
    )
    assert manifest["plugin_ref"] == "workspace:default"
    assert called is False

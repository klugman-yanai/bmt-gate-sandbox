from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.fixtures.paths import StagePaths
from tests.support.sentinels import FAKE_BUCKET, SYNTH_BMT_SLUG, SYNTH_PROJECT
from tools.bmt.publisher import publish_bmt
from tools.bmt.scaffold import add_bmt, add_project

pytestmark = pytest.mark.integration


def test_publish_bmt_creates_immutable_bundle_updates_manifest_and_syncs(tmp_path: Path, monkeypatch) -> None:
    sp = StagePaths(tmp_path / "gcp" / "stage")
    add_project(SYNTH_PROJECT, stage_root=sp.root, dry_run=False)
    add_bmt(SYNTH_PROJECT, SYNTH_BMT_SLUG, stage_root=sp.root, plugin="default")

    plugin_file = sp.plugin_workspace(SYNTH_PROJECT, "default") / "src" / f"{SYNTH_PROJECT}_plugin" / "plugin.py"
    plugin_file.write_text(
        plugin_file.read_text(encoding="utf-8") + "\nPLUGIN_SENTINEL = 'published'\n",
        encoding="utf-8",
    )

    synced: list[str] = []

    def _fake_sync(*, bucket: str, project: str, stage_root: Path | None = None) -> int:
        assert stage_root == sp.root
        assert bucket == FAKE_BUCKET
        synced.append(project)
        return 0

    monkeypatch.setenv("GCS_BUCKET", FAKE_BUCKET)
    monkeypatch.setattr("tools.bmt.publisher.sync_project", _fake_sync)

    result = publish_bmt(stage_root=sp.root, project=SYNTH_PROJECT, bmt_slug=SYNTH_BMT_SLUG)

    assert result.plugin_ref.startswith("published:default:sha256-")
    assert result.published_dir.is_dir()
    published_manifest = json.loads((result.published_dir / "plugin.json").read_text(encoding="utf-8"))
    assert published_manifest["entrypoint"] == f"{SYNTH_PROJECT}_plugin:{SYNTH_PROJECT.title()}Plugin"
    bmt_manifest = json.loads(sp.bmt_manifest(SYNTH_PROJECT, SYNTH_BMT_SLUG).read_text(encoding="utf-8"))
    assert bmt_manifest["plugin_ref"] == result.plugin_ref
    assert bmt_manifest["enabled"] is True
    assert synced == [SYNTH_PROJECT]


def test_publish_bmt_can_skip_sync(tmp_path: Path, monkeypatch) -> None:
    sp = StagePaths(tmp_path / "gcp" / "stage")
    add_project(SYNTH_PROJECT, stage_root=sp.root, dry_run=False)
    add_bmt(SYNTH_PROJECT, SYNTH_BMT_SLUG, stage_root=sp.root, plugin="default")

    called = False

    def _fake_sync(**_: object) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr("tools.bmt.publisher.sync_project", _fake_sync)

    publish_bmt(stage_root=sp.root, project=SYNTH_PROJECT, bmt_slug=SYNTH_BMT_SLUG, sync=False)

    assert called is False


def test_publish_bmt_fails_before_sync_when_workspace_plugin_is_invalid(tmp_path: Path, monkeypatch) -> None:
    sp = StagePaths(tmp_path / "gcp" / "stage")
    add_project(SYNTH_PROJECT, stage_root=sp.root, dry_run=False)
    add_bmt(SYNTH_PROJECT, SYNTH_BMT_SLUG, stage_root=sp.root, plugin="default")

    plugin_file = sp.plugin_workspace(SYNTH_PROJECT, "default") / "src" / f"{SYNTH_PROJECT}_plugin" / "plugin.py"
    plugin_file.write_text("not valid python(", encoding="utf-8")

    called = False

    def _fake_sync(**_: object) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr("tools.bmt.publisher.sync_project", _fake_sync)

    with pytest.raises(SyntaxError, match="was never closed"):
        publish_bmt(stage_root=sp.root, project=SYNTH_PROJECT, bmt_slug=SYNTH_BMT_SLUG)

    manifest = json.loads(sp.bmt_manifest(SYNTH_PROJECT, SYNTH_BMT_SLUG).read_text(encoding="utf-8"))
    assert manifest["plugin_ref"] == "workspace:default"
    assert called is False

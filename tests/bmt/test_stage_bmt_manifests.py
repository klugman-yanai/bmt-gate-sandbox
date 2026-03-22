"""Validate committed `gcp/stage` BMT manifests against runtime models.

Discovery matches ``build_plan`` (``projects/*/bmts/*/bmt.json`` under the stage root).
This suite performs a **full-tree scan**; a future optional **git-diff-only** mode could
accelerate PRs but must not replace full validation on the default branch.

Fast tests (default): parse, path consistency, ``project.json``, published bundle /
workspace layout rules.

Optional tiers: ``@pytest.mark.bmt_plugin_load`` (import published plugins) and
``@pytest.mark.integration`` (single ``build_plan`` smoke over the tree).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from gcp.image.runtime.models import BmtManifest, PluginManifest, ProjectManifest, StageRuntimePaths, WorkflowRequest
from gcp.image.runtime.planning import PlanOptions, build_plan
from gcp.image.runtime.plugin_loader import load_plugin
from gcp.image.runtime.plugin_publisher import plugin_digest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STAGE_ROOT = _REPO_ROOT / "gcp" / "stage"


@dataclass(frozen=True, slots=True)
class StageBmtRecord:
    """One discovered ``bmt.json`` under the stage tree."""

    manifest_path: Path
    """Path relative to ``gcp/stage``, posix, for stable pytest ids."""

    id_posix: str


def _discover_stage_bmt_manifests(stage_root: Path) -> list[StageBmtRecord]:
    if not stage_root.is_dir():
        return []
    out: list[StageBmtRecord] = []
    for path in sorted(stage_root.glob("projects/*/bmts/*/bmt.json")):
        rel = path.relative_to(stage_root).as_posix()
        out.append(StageBmtRecord(manifest_path=path, id_posix=rel))
    return out


def _manifest_enabled(manifest_path: Path) -> bool:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return bool(data.get("enabled", False))


_RECORDS = _discover_stage_bmt_manifests(_STAGE_ROOT)
_ENABLED_RECORDS = [r for r in _RECORDS if _manifest_enabled(r.manifest_path)]


@pytest.mark.unit
def test_stage_tree_has_bmt_manifests(repo_stage_root: Path) -> None:
    """Guard: parametrized tests vanish if the tree is empty—fail loudly instead."""
    assert _RECORDS, (
        "Expected at least one projects/*/bmts/*/bmt.json under gcp/stage; "
        "an empty tree would skip all parametrized manifest checks."
    )
    assert repo_stage_root.resolve() == _STAGE_ROOT.resolve()


def _assert_path_matches_manifest(stage_root: Path, manifest_path: Path, manifest: BmtManifest) -> None:
    rel = manifest_path.relative_to(stage_root)
    parts = rel.parts
    assert len(parts) == 5, f"Unexpected manifest path shape: {rel}"
    assert parts[0] == "projects" and parts[2] == "bmts" and parts[4] == "bmt.json", (
        f"Unexpected manifest path segments: {rel}"
    )
    assert parts[1] == manifest.project, f"path project {parts[1]!r} != manifest.project {manifest.project!r}"
    assert parts[3] == manifest.bmt_slug, f"path slug {parts[3]!r} != manifest.bmt_slug {manifest.bmt_slug!r}"


def _validate_published_bundle(stage_root: Path, manifest: BmtManifest) -> None:
    assert manifest.plugin_ref.startswith("published:"), (
        f"enabled BMT must use published: plugin_ref, got {manifest.plugin_ref!r}"
    )
    parts = manifest.plugin_ref.split(":", 2)
    assert len(parts) == 3, f"Malformed published ref: {manifest.plugin_ref!r}"
    _, plugin_name, digest_segment = parts
    published_root = stage_root / "projects" / manifest.project / "plugins" / plugin_name / digest_segment
    plugin_json = published_root / "plugin.json"
    assert plugin_json.is_file(), f"Missing published plugin bundle: {plugin_json}"
    raw = json.loads(plugin_json.read_text(encoding="utf-8"))
    PluginManifest.model_validate(raw)
    # Digest in path must match content (same as planner / publisher).
    assert plugin_digest(published_root) == digest_segment.removeprefix("sha256-"), (
        f"plugin digest mismatch for {published_root}: path digest does not match tree content"
    )


def _validate_workspace_ref(stage_root: Path, manifest: BmtManifest) -> None:
    if not manifest.plugin_ref.startswith("workspace:"):
        return
    name = manifest.plugin_ref.split(":", 1)[1]
    ws = stage_root / "projects" / manifest.project / "plugin_workspaces" / name
    assert ws.is_dir(), f"workspace plugin_ref points to missing directory: {ws}"


@pytest.mark.unit
@pytest.mark.parametrize("record", _RECORDS, ids=lambda r: r.id_posix)
def test_committed_bmt_manifest_static(
    repo_stage_root: Path,
    record: StageBmtRecord,
) -> None:
    """Parse manifest, path consistency, ``project.json``, and plugin layout rules."""
    manifest_path = record.manifest_path
    assert manifest_path.is_file(), f"Manifest not found: {manifest_path}"

    raw_text = manifest_path.read_text(encoding="utf-8")
    manifest = BmtManifest.model_validate(json.loads(raw_text))

    _assert_path_matches_manifest(repo_stage_root, manifest_path, manifest)

    project_json = repo_stage_root / "projects" / manifest.project / "project.json"
    assert project_json.is_file(), f"Missing project.json for project {manifest.project}: {project_json}"
    ProjectManifest.model_validate(json.loads(project_json.read_text(encoding="utf-8")))

    if manifest.enabled:
        assert manifest.plugin_ref.startswith("published:"), (
            "enabled BMTs must use a published plugin ref (not workspace:) for CI/prod parity"
        )
        _validate_published_bundle(repo_stage_root, manifest)
    else:
        _validate_workspace_ref(repo_stage_root, manifest)


@pytest.mark.bmt_plugin_load
@pytest.mark.parametrize("record", _ENABLED_RECORDS, ids=lambda r: r.id_posix)
def test_enabled_bmt_loads_published_plugin(
    repo_stage_root: Path,
    record: StageBmtRecord,
) -> None:
    """``load_plugin`` with ``allow_workspace=False`` (same as planner)."""
    raw_text = record.manifest_path.read_text(encoding="utf-8")
    manifest = BmtManifest.model_validate(json.loads(raw_text))
    assert manifest.enabled
    plugin, _root = load_plugin(
        repo_stage_root,
        manifest.project,
        manifest.plugin_ref,
        allow_workspace=False,
    )
    assert plugin is not None


@pytest.mark.integration
def test_build_plan_smoke_includes_enabled_legs(
    repo_stage_root: Path,
    tmp_path: Path,
) -> None:
    """Single ``build_plan`` over the committed tree (enabled legs only)."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    plan = build_plan(
        runtime=StageRuntimePaths(stage_root=repo_stage_root, workspace_root=workspace_root),
        options=PlanOptions(
            request=WorkflowRequest(workflow_run_id="pytest-stage-verify"),
            allow_workspace_plugins=False,
        ),
    )
    assert len(plan.legs) == len(_ENABLED_RECORDS)
    slugs = {leg.bmt_slug for leg in plan.legs}
    for record in _ENABLED_RECORDS:
        m = BmtManifest.model_validate(json.loads(record.manifest_path.read_text(encoding="utf-8")))
        assert m.bmt_slug in slugs

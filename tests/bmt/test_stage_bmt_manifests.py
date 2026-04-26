"""Validate committed plugins BMT manifests against runtime models.

Discovery matches ``build_plan`` — supports both nested (``projects/*/bmts/*/bmt.json``)
and flat (``projects/*/*.json``) layouts under the stage root.
This suite performs a **full-tree scan**; a future optional **git-diff-only** mode could
accelerate PRs but must not replace full validation on the default branch.

Fast tests (default): parse, path consistency, ``project.json``, plugin layout rules.

Optional tiers: ``@pytest.mark.bmt_plugin_load`` (import direct plugins) and
``@pytest.mark.integration`` (single ``build_plan`` smoke over the tree).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from runtime.models import BmtManifest, ProjectManifest, StageRuntimePaths, WorkflowRequest
from runtime.planning import _FLAT_EXCLUDE, PlanOptions, build_plan
from runtime.plugin_loader import load_plugin

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STAGE_ROOT = _REPO_ROOT / "plugins"


@dataclass(frozen=True, slots=True)
class StageBmtRecord:
    """One discovered BMT manifest under the stage tree."""

    manifest_path: Path
    """Absolute path to the manifest file."""

    id_posix: str
    """Path relative to stage root, posix, for stable pytest ids."""

    is_flat: bool
    """True if this is a flat layout manifest (projects/sk/false_alarms.json)."""


def _discover_stage_bmt_manifests(stage_root: Path) -> list[StageBmtRecord]:
    if not stage_root.is_dir():
        return []
    out: list[StageBmtRecord] = []
    projects_root = stage_root / "projects"
    # Legacy nested layout: projects/sk/bmts/false_alarms/bmt.json
    for path in sorted(projects_root.glob("*/bmts/*/bmt.json")):
        rel = path.relative_to(stage_root).as_posix()
        out.append(StageBmtRecord(manifest_path=path, id_posix=rel, is_flat=False))
    # New flat layout: projects/sk/false_alarms.json
    # Exclude well-known non-BMT files and any _* names.
    for path in sorted(projects_root.glob("*/*.json")):
        if path.name not in _FLAT_EXCLUDE and not path.name.startswith("_"):
            rel = path.relative_to(stage_root).as_posix()
            out.append(StageBmtRecord(manifest_path=path, id_posix=rel, is_flat=True))
    return out


def _manifest_enabled(record: StageBmtRecord) -> bool:
    data = json.loads(record.manifest_path.read_text(encoding="utf-8"))
    return bool(data.get("enabled", False))


_RECORDS = _discover_stage_bmt_manifests(_STAGE_ROOT)
_ENABLED_RECORDS = [r for r in _RECORDS if _manifest_enabled(r)]


@pytest.mark.unit
def test_stage_tree_has_bmt_manifests(repo_stage_root: Path) -> None:
    """Guard: parametrized tests vanish if the tree is empty—fail loudly instead."""
    assert _RECORDS, (
        "Expected at least one BMT manifest under plugins/projects "
        "(either projects/*/bmts/*/bmt.json or projects/*/*.json); "
        "an empty tree would skip all parametrized manifest checks."
    )
    assert repo_stage_root.resolve() == _STAGE_ROOT.resolve()


def _assert_nested_path_matches_manifest(stage_root: Path, manifest_path: Path, manifest: BmtManifest) -> None:
    rel = manifest_path.relative_to(stage_root)
    parts = rel.parts
    assert len(parts) == 5, f"Unexpected manifest path shape: {rel}"
    assert parts[0] == "projects" and parts[2] == "bmts" and parts[4] == "bmt.json", (
        f"Unexpected manifest path segments: {rel}"
    )
    assert parts[1] == manifest.project, f"path project {parts[1]!r} != manifest.project {manifest.project!r}"
    assert parts[3] == manifest.bmt_slug, f"path slug {parts[3]!r} != manifest.bmt_slug {manifest.bmt_slug!r}"


def _assert_flat_path_matches_manifest(stage_root: Path, manifest_path: Path, manifest: BmtManifest) -> None:
    rel = manifest_path.relative_to(stage_root)
    parts = rel.parts
    assert len(parts) == 3, f"Unexpected flat manifest path shape: {rel}"
    assert parts[0] == "projects", f"Expected 'projects' first segment, got: {rel}"
    assert parts[1] == manifest.project, f"path project {parts[1]!r} != manifest.project {manifest.project!r}"
    assert parts[2] == f"{manifest.bmt_slug}.json", f"path file {parts[2]!r} != expected {manifest.bmt_slug}.json"


def _validate_direct_plugin(stage_root: Path, manifest: BmtManifest) -> None:
    """Flat-layout manifests use plugin_ref='direct': plugin.py must exist at project root."""
    assert manifest.plugin_ref == "direct", (
        f"flat-layout enabled BMT must use plugin_ref='direct', got {manifest.plugin_ref!r}"
    )
    plugin_py = stage_root / "projects" / manifest.project / "plugin.py"
    assert plugin_py.is_file(), f"Missing plugin.py for direct plugin_ref: {plugin_py}"


@pytest.mark.unit
@pytest.mark.parametrize("record", _RECORDS, ids=lambda r: r.id_posix)
def test_committed_bmt_manifest_static(
    repo_stage_root: Path,
    record: StageBmtRecord,
) -> None:
    """Parse manifest, path consistency, ``project.json``, and plugin layout rules."""
    manifest_path = record.manifest_path
    assert manifest_path.is_file(), f"Manifest not found: {manifest_path}"

    if record.is_flat:
        manifest = BmtManifest.from_flat_file(manifest_path)
        _assert_flat_path_matches_manifest(repo_stage_root, manifest_path, manifest)
    else:
        raw_text = manifest_path.read_text(encoding="utf-8")
        manifest = BmtManifest.model_validate(json.loads(raw_text))
        _assert_nested_path_matches_manifest(repo_stage_root, manifest_path, manifest)

    project_json = repo_stage_root / "projects" / manifest.project / "project.json"
    assert project_json.is_file(), f"Missing project.json for project {manifest.project}: {project_json}"
    ProjectManifest.model_validate(json.loads(project_json.read_text(encoding="utf-8")))

    if manifest.enabled:
        if record.is_flat:
            _validate_direct_plugin(repo_stage_root, manifest)
        else:
            assert manifest.plugin_ref.startswith("published:"), (
                "enabled nested-layout BMTs must use a published plugin ref for CI/prod parity"
            )


@pytest.mark.bmt_plugin_load
@pytest.mark.parametrize("record", _ENABLED_RECORDS, ids=lambda r: r.id_posix)
def test_enabled_bmt_loads_plugin(
    repo_stage_root: Path,
    record: StageBmtRecord,
) -> None:
    """``load_plugin`` resolves correctly for both direct and published refs."""
    if record.is_flat:
        manifest = BmtManifest.from_flat_file(record.manifest_path)
    else:
        manifest = BmtManifest.model_validate(json.loads(record.manifest_path.read_text(encoding="utf-8")))
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
        if record.is_flat:
            m = BmtManifest.from_flat_file(record.manifest_path)
        else:
            m = BmtManifest.model_validate(json.loads(record.manifest_path.read_text(encoding="utf-8")))
        assert m.bmt_slug in slugs

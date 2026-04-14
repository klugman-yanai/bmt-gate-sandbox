"""CLI-facing wrappers for local validation, immutable plugin publishing, and sync."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.models import BmtManifest, ProjectManifest
from runtime.plugin_loader import load_plugin_direct
from runtime.plugin_publisher import PublishResult, publish_workspace_plugin
from tools.remote.bucket_sync_project import BucketSyncProject
from tools.repo.paths import DEFAULT_STAGE_ROOT, repo_root
from tools.shared.bucket_env import bucket_from_env


def _stage_root(stage_root: Path | None) -> Path:
    return stage_root if stage_root is not None else repo_root() / DEFAULT_STAGE_ROOT


def _project_root(stage_root: Path, project: str) -> Path:
    return stage_root / "projects" / project


def _manifest_path(stage_root: Path, project: str, bmt_slug: str) -> Path:
    return _project_root(stage_root, project) / "bmts" / bmt_slug / "bmt.json"


def _load_bmt_manifest(stage_root: Path, project: str, bmt_slug: str) -> BmtManifest:
    return BmtManifest.model_validate(
        json.loads(_manifest_path(stage_root, project, bmt_slug).read_text(encoding="utf-8"))
    )


def _plugin_name_for_publish(plugin_ref: str) -> str:
    if plugin_ref.startswith("workspace:"):
        return plugin_ref.split(":", 1)[1]
    if plugin_ref.startswith("published:"):
        return plugin_ref.split(":", 2)[1]
    raise ValueError(f"Unsupported plugin_ref for publish: {plugin_ref}")


def _load_workspace_plugin(workspace_dir: Path) -> None:
    """Validate that the workspace plugin loads without errors.

    Workspace plugins have a plugin.json with package_root and entrypoint.
    We locate the package directory (plugin.json["package_root"]) and use
    load_plugin_direct to verify the BmtPlugin subclass is importable.
    """
    plugin_json_path = workspace_dir / "plugin.json"
    plugin_json = json.loads(plugin_json_path.read_text(encoding="utf-8"))
    package_root = plugin_json.get("package_root", "src")
    entrypoint: str = plugin_json["entrypoint"]
    pkg_name = entrypoint.split(":", maxsplit=1)[0]
    pkg_dir = workspace_dir / package_root / pkg_name
    load_plugin_direct(pkg_dir)


def validate_workspace_plugin(*, stage_root: Path, project: str, bmt_slug: str) -> str:
    project_root = _project_root(stage_root, project)
    ProjectManifest.model_validate(json.loads((project_root / "project.json").read_text(encoding="utf-8")))
    bmt_manifest = _load_bmt_manifest(stage_root, project, bmt_slug)
    plugin_name = _plugin_name_for_publish(bmt_manifest.plugin_ref)
    workspace_dir = project_root / "plugin_workspaces" / plugin_name
    _load_workspace_plugin(workspace_dir)
    return plugin_name


def sync_project(*, bucket: str, project: str, stage_root: Path | None = None) -> int:
    return BucketSyncProject().run(bucket=bucket, project=project, stage_root=stage_root)


def publish_bmt(
    *,
    stage_root: Path | None = None,
    project: str,
    bmt_slug: str,
    sync: bool = True,
) -> PublishResult:
    resolved_stage_root = _stage_root(stage_root)
    plugin_name = validate_workspace_plugin(stage_root=resolved_stage_root, project=project, bmt_slug=bmt_slug)

    result = publish_workspace_plugin(resolved_stage_root, project, plugin_name)

    manifest_path = _manifest_path(resolved_stage_root, project, bmt_slug)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["plugin_ref"] = result.plugin_ref
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if sync:
        bucket = bucket_from_env()
        if not bucket:
            raise RuntimeError("Unable to resolve GCS_BUCKET from env or GitHub repo vars")
        rc = sync_project(bucket=bucket, project=project, stage_root=resolved_stage_root)
        if rc != 0:
            raise RuntimeError(f"Failed to sync project {project} to gs://{bucket}")

    return result

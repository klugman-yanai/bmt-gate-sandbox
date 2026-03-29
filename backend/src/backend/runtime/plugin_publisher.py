"""Publish mutable workspace plugins into immutable bundles."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.runtime.models import PluginManifest
from backend.runtime.stage_paths import published_dir_for_new_publish, resolve_plugin_workspace_dir


def plugin_digest(plugin_root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(p for p in plugin_root.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(plugin_root).as_posix().encode("utf-8")
        hasher.update(rel)
        hasher.update(b"\n")
        hasher.update(path.read_bytes())
        hasher.update(b"\n")
    return hasher.hexdigest()


def _publish_source_dir(workspace_dir: Path) -> tuple[Path, Path | None]:
    """Return (root to digest/copy, temp_dir_or_none_if_cleanup_needed).

    When the workspace is the whole project tree (``plugin.json`` + ``bmts/`` at the same level),
    only ``plugin.json`` and the declared ``package_root`` directory are published — not
    ``lib/``, datasets, or manifests.
    """
    manifest_path = workspace_dir / "plugin.json"
    if not manifest_path.is_file():
        return workspace_dir, None
    has_bmt_tree = (workspace_dir / "bmts").is_dir() or (workspace_dir / "benchmarks").is_dir()
    if not has_bmt_tree:
        return workspace_dir, None
    manifest = PluginManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    package_dir = workspace_dir / manifest.package_root
    if not package_dir.is_dir():
        raise FileNotFoundError(f"package_root {manifest.package_root!r} missing under {workspace_dir}")
    tmp = Path(tempfile.mkdtemp(prefix="bmt-plugin-publish-"))
    try:
        shutil.copy2(manifest_path, tmp / "plugin.json")
        shutil.copytree(package_dir, tmp / manifest.package_root, symlinks=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp, tmp


@dataclass(frozen=True, slots=True)
class PublishResult:
    plugin_name: str
    digest: str
    plugin_ref: str
    published_dir: Path


def publish_workspace_plugin(stage_root: Path, project: str, plugin_name: str) -> PublishResult:
    workspace_dir = resolve_plugin_workspace_dir(stage_root, project, plugin_name)
    source_dir, tmp_cleanup = _publish_source_dir(workspace_dir)
    try:
        digest = plugin_digest(source_dir)
        published_dir = published_dir_for_new_publish(stage_root, project, plugin_name, digest)
        if published_dir.exists():
            shutil.rmtree(published_dir)
        published_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, published_dir, symlinks=True)
        return PublishResult(
            plugin_name=plugin_name,
            digest=digest,
            plugin_ref=f"published:{plugin_name}:sha256-{digest}",
            published_dir=published_dir,
        )
    finally:
        if tmp_cleanup is not None:
            shutil.rmtree(tmp_cleanup, ignore_errors=True)

"""Publish mutable workspace plugins into immutable bundles."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True, slots=True)
class PublishResult:
    plugin_name: str
    digest: str
    plugin_ref: str
    published_dir: Path


def publish_workspace_plugin(stage_root: Path, project: str, plugin_name: str) -> PublishResult:
    workspace_dir = stage_root / "projects" / project / "plugin_workspaces" / plugin_name
    digest = plugin_digest(workspace_dir)
    published_dir = stage_root / "projects" / project / "plugins" / plugin_name / f"sha256-{digest}"
    if published_dir.exists():
        shutil.rmtree(published_dir)
    published_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(workspace_dir, published_dir)
    return PublishResult(
        plugin_name=plugin_name,
        digest=digest,
        plugin_ref=f"published:{plugin_name}:sha256-{digest}",
        published_dir=published_dir,
    )

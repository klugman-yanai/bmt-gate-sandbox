"""Load a plugin instance from a workspace or immutable bundle."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from gcp.image.runtime.models import PluginManifest
from gcp.image.runtime.plugin_errors import ManifestValidationError, PluginLoadError, WorkspacePluginRefError
from gcp.image.runtime.sdk.plugin import BmtPlugin
from gcp.image.runtime.stage_paths import resolve_plugin_workspace_dir, resolve_published_plugin_dir

__all__ = [
    "ManifestValidationError",
    "PluginLoadError",
    "WorkspacePluginRefError",
    "load_plugin",
]


def _resolve_plugin_root(stage_root: Path, project: str, plugin_ref: str, *, allow_workspace: bool) -> Path:
    if plugin_ref.startswith("workspace:"):
        if not allow_workspace:
            raise WorkspacePluginRefError(f"Workspace plugin refs are not allowed here: {plugin_ref}")
        plugin_name = plugin_ref.split(":", 1)[1]
        return resolve_plugin_workspace_dir(stage_root, project, plugin_name)
    if plugin_ref.startswith("published:"):
        _, plugin_name, digest_segment = plugin_ref.split(":", 2)
        return resolve_published_plugin_dir(stage_root, project, plugin_name, digest_segment)
    raise ManifestValidationError(f"Unsupported plugin_ref: {plugin_ref}")


@contextmanager
def _plugin_path(path: Path) -> Iterator[None]:
    sys.path.insert(0, str(path))
    try:
        yield
    finally:
        if sys.path and sys.path[0] == str(path):
            sys.path.pop(0)
        else:
            sys.path[:] = [entry for entry in sys.path if entry != str(path)]


def load_plugin(stage_root: Path, project: str, plugin_ref: str, *, allow_workspace: bool) -> tuple[BmtPlugin, Path]:
    plugin_root = _resolve_plugin_root(stage_root, project, plugin_ref, allow_workspace=allow_workspace)
    manifest_path = plugin_root / "plugin.json"
    if not manifest_path.is_file():
        raise PluginLoadError(f"Missing plugin manifest: {manifest_path}")
    manifest = PluginManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    module_name, class_name = manifest.entrypoint.split(":", 1)
    package_root = plugin_root / manifest.package_root
    with _plugin_path(package_root):
        importlib.invalidate_caches()
        stale_modules = [name for name in sys.modules if name == module_name or name.startswith(f"{module_name}.")]
        for name in stale_modules:
            sys.modules.pop(name, None)
        module = importlib.import_module(module_name)
    plugin_cls = getattr(module, class_name, None)
    if plugin_cls is None:
        raise PluginLoadError(f"Entrypoint not found: {manifest.entrypoint}")
    plugin = plugin_cls()
    if not isinstance(plugin, BmtPlugin):
        raise PluginLoadError(f"Entrypoint is not a BmtPlugin: {manifest.entrypoint}")
    plugin.validate_against_loaded_manifest(manifest)
    return plugin, plugin_root

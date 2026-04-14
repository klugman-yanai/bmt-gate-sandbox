"""Load a plugin instance from a workspace or immutable bundle."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bmt_sdk import BmtPlugin

from runtime.models import PluginManifest


class ManifestValidationError(RuntimeError):
    pass


class PluginLoadError(RuntimeError):
    pass


class WorkspacePluginRefError(RuntimeError):
    pass


def _resolve_plugin_root(stage_root: Path, project: str, plugin_ref: str, *, allow_workspace: bool) -> Path:
    if plugin_ref.startswith("workspace:"):
        if not allow_workspace:
            raise WorkspacePluginRefError(f"Workspace plugin refs are not allowed here: {plugin_ref}")
        plugin_name = plugin_ref.split(":", 1)[1]
        return stage_root / "projects" / project / "plugin_workspaces" / plugin_name
    if plugin_ref.startswith("published:"):
        _, plugin_name, digest = plugin_ref.split(":", 2)
        return stage_root / "projects" / project / "plugins" / plugin_name / digest
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


def load_plugin_direct(project_dir: Path) -> tuple[BmtPlugin, Path]:
    """Load a BmtPlugin subclass from <project_dir>/plugin.py by convention.

    Adds project_dir to sys.path temporarily so sibling modules (helpers.py, etc.)
    are importable. Returns (plugin_instance, project_dir).

    Raises:
        FileNotFoundError: if plugin.py does not exist.
        RuntimeError: if plugin.py does not contain exactly one BmtPlugin subclass.
    """
    plugin_py = project_dir / "plugin.py"
    if not plugin_py.is_file():
        raise FileNotFoundError(f"Expected plugin.py at {plugin_py}")

    module_name = f"bmt_plugin_{project_dir.name}_{id(project_dir)}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create module spec for {plugin_py}")

    path_str = str(project_dir)
    added = path_str not in sys.path
    if added:
        sys.path.insert(0, path_str)
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    finally:
        if added and path_str in sys.path:
            sys.path.remove(path_str)

    candidates = [
        cls
        for cls in vars(module).values()
        if isinstance(cls, type) and issubclass(cls, BmtPlugin) and cls is not BmtPlugin
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"plugins/{project_dir.name}/plugin.py must define exactly one BmtPlugin subclass, "
            f"found {len(candidates)}: {[c.__name__ for c in candidates]}"
        )
    return candidates[0](), project_dir


def load_plugin(stage_root: Path, project: str, plugin_ref: str, *, allow_workspace: bool) -> tuple[BmtPlugin, Path]:
    if plugin_ref == "direct" or not plugin_ref:
        project_dir = stage_root / "projects" / project  # still projects/ until Phase 4
        return load_plugin_direct(project_dir)
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
    return plugin, plugin_root

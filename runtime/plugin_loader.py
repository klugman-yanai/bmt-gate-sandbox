"""Load a plugin instance from plugin.py by convention."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from bmt_sdk import BmtPlugin


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


def load_plugin(
    stage_root: Path,
    project: str,
    plugin_ref: str = "direct",  # noqa: ARG001 — API compat; ignored, always uses direct loading
    *,
    allow_workspace: bool = True,  # noqa: ARG001 — API compat; direct loading ignores allow_workspace
) -> tuple[BmtPlugin, Path]:
    """Load a BmtPlugin from plugins/<project>/plugin.py.

    plugin_ref is accepted for API compatibility but ignored — all plugins
    load directly from plugin.py by convention.
    allow_workspace is accepted for API compatibility but ignored.
    """
    project_dir = stage_root / "projects" / project
    return load_plugin_direct(project_dir)

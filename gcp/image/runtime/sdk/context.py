"""Plugin execution context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gcp.image.runtime.models import BmtManifest, ProjectManifest


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    project_manifest: ProjectManifest
    bmt_manifest: BmtManifest
    plugin_root: Path
    workspace_root: Path
    dataset_root: Path
    outputs_root: Path
    logs_root: Path
    runner_path: Path | None = None
    deps_root: Path | None = None

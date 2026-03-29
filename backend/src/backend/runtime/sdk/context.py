"""Immutable execution context passed into every plugin lifecycle hook."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backend.runtime.models import BmtManifest, ProjectManifest


class ExecutionContext(BaseModel):
    """Everything a plugin needs for one planned leg, resolved from manifests and runtime paths.

    Frozen Pydantic model: treat instances as value objects; do not mutate in place.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra="forbid")

    project_manifest: ProjectManifest = Field(description="Tenant-level defaults and metadata.")
    bmt_manifest: BmtManifest = Field(description="This leg's benchmark manifest (``bmt.json``).")
    plugin_root: Path = Field(description="Filesystem root of the loaded plugin package.")
    workspace_root: Path = Field(description="Scratch workspace for this run (outputs, logs, temp).")
    dataset_root: Path = Field(description="Staged inputs for this leg (often WAVs under ``inputs_prefix``).")
    outputs_root: Path = Field(description="Where the plugin should write per-run artifacts.")
    logs_root: Path = Field(description="Per-run logs directory.")
    runner_path: Path | None = Field(
        default=None,
        description="Resolved native runner binary when ``runner.uri`` is set in the manifest.",
    )
    deps_root: Path | None = Field(
        default=None,
        description="Directory prepended for shared native libraries (``LD_LIBRARY_PATH`` fragment).",
    )

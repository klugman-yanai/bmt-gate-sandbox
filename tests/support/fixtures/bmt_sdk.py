"""Reusable builders for BMT plugin / SDK tests."""

from __future__ import annotations

from pathlib import Path

from backend.config.value_types import as_results_path
from backend.runtime.models import BmtManifest, ProjectManifest, RunnerConfig
from backend.runtime.sdk.context import ExecutionContext


def minimal_execution_context(tmp_path: Path) -> ExecutionContext:
    """A small :class:`ExecutionContext` rooted under ``tmp_path`` (unit tests only)."""
    ds = tmp_path / "dataset"
    ds.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    pm = ProjectManifest(project="p", default_plugin="main")
    bm = BmtManifest(
        project="p",
        bmt_slug="bench",
        bmt_id="id",
        plugin_ref="workspace:main",
        inputs_prefix="projects/p/inputs/bench",
        results_path=as_results_path("projects/p/results/bench"),
        outputs_prefix="projects/p/outputs/bench",
        runner=RunnerConfig(template_path="backend/src/backend/runtime/assets/runner_input.template.json"),
        plugin_config={"pass_threshold": 2.5, "extra_ignored": 1},
    )
    return ExecutionContext(
        project_manifest=pm,
        bmt_manifest=bm,
        plugin_root=tmp_path / "plugin",
        workspace_root=ws,
        dataset_root=ds,
        outputs_root=out,
        logs_root=logs,
        runner_path=tmp_path / "runner_bin",
    )

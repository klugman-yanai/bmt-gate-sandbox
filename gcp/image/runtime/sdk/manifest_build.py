"""Reference factory for a validated :class:`~gcp.image.runtime.models.BmtManifest` (``bmt.json`` wire shape)."""

from __future__ import annotations

import uuid
from typing import Any

from gcp.image.config.value_types import as_results_path
from gcp.image.runtime.models import BmtManifest, ExecutionConfig, RunnerConfig


def build_default_bmt_manifest(
    project: str,
    benchmark_folder_name: str,
    *,
    plugin_ref: str = "workspace:default",
    enabled: bool = False,
    bmt_id: str | None = None,
    plugin_config: dict[str, Any] | None = None,
    runner: RunnerConfig | None = None,
    execution: ExecutionConfig | None = None,
) -> BmtManifest:
    """Build the same default shape as scaffolded ``bmt.json`` (paths follow the benchmark folder name).

    The on-disk folder under ``bmts/`` must match ``benchmark_folder_name``; the JSON field ``bmt_slug``
    is set to the same value (runtime/planner expect them to match).
    """
    resolved_id = bmt_id or str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"https://bmt/{project}/{benchmark_folder_name}")
    )
    return BmtManifest(
        schema_version=1,
        project=project,
        bmt_slug=benchmark_folder_name,
        bmt_id=resolved_id,
        enabled=enabled,
        plugin_ref=plugin_ref,
        inputs_prefix=f"projects/{project}/inputs/{benchmark_folder_name}",
        results_path=as_results_path(f"projects/{project}/results/{benchmark_folder_name}"),
        outputs_prefix=f"projects/{project}/outputs/{benchmark_folder_name}",
        runner=runner or RunnerConfig(),
        execution=execution or ExecutionConfig(),
        plugin_config=dict(plugin_config) if plugin_config is not None else {"pass_threshold": 1.0},
    )

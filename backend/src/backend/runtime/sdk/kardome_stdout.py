"""Glue for plugins that drive :class:`~backend.runtime.legacy_kardome.LegacyKardomeStdoutExecutor`."""

from __future__ import annotations

from pydantic import BaseModel

from backend.runtime.legacy_kardome import LegacyKardomeStdoutConfig
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.plugin import BmtPlugin
from backend.runtime.sdk.results import PreparedAssets


def legacy_stdout_config_from_context[TParse: BaseModel](
    plugin: BmtPlugin,
    context: ExecutionContext,
    prepared: PreparedAssets,
    *,
    parse_model: type[TParse],
) -> LegacyKardomeStdoutConfig:
    """Build stdout Kardome config from context + validated parse settings (typical ``execute`` boilerplate)."""
    validated = plugin.parse_plugin_config(context, parse_model)
    cfg = context.bmt_manifest.plugin_config
    return LegacyKardomeStdoutConfig(
        runner_path=prepared.runner_path or plugin.require_runner(context),
        template_path=plugin.resolve_runner_template_path(context),
        dataset_root=context.dataset_root,
        runtime_root=context.workspace_root,
        outputs_root=context.outputs_root,
        logs_root=context.logs_root,
        parsing=validated.model_dump(mode="python", exclude_none=True),
        enable_overrides=dict(cfg.get("enable_overrides", {})),
        num_source_test=cfg.get("num_source_test"),
        runner_env=plugin.runner_env_with_deps(context),
    )

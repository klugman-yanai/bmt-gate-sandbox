"""Stable plugin SDK surface (image-baked; see docs/bmt-python-contributor-protocol.md)."""

from __future__ import annotations

from gcp.image.runtime.models import (
    BmtManifest,
    ExecutionConfig,
    PluginManifest,
    ProjectManifest,
    RunnerConfig,
)
from gcp.image.runtime.sdk.compatibility import SUPPORTED_PLUGIN_API_VERSIONS, ensure_plugin_api_version_supported
from gcp.image.runtime.sdk.context import ExecutionContext
from gcp.image.runtime.sdk.kardome import AdaptiveKardomeExecutor
from gcp.image.runtime.sdk.kardome_runner_json import (
    parse_kardome_runner_json_file,
    parse_kardome_runner_json_payload,
)
from gcp.image.runtime.sdk.manifest_build import build_default_bmt_manifest
from gcp.image.runtime.sdk.plugin import (
    PLUGIN_EXECUTE_EXCEPTION_RAW_KEY,
    BmtPlugin,
)
from gcp.image.runtime.sdk.protocols import BmtPluginProtocol
from gcp.image.runtime.sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from gcp.image.runtime.sdk.subprocess_batch import run_subprocess_in_workspace

__all__ = [
    "PLUGIN_EXECUTE_EXCEPTION_RAW_KEY",
    "SUPPORTED_PLUGIN_API_VERSIONS",
    "AdaptiveKardomeExecutor",
    "BmtManifest",
    "BmtPlugin",
    "BmtPluginProtocol",
    "CaseResult",
    "ExecutionConfig",
    "ExecutionContext",
    "ExecutionResult",
    "PluginManifest",
    "PreparedAssets",
    "ProjectManifest",
    "RunnerConfig",
    "ScoreResult",
    "VerdictResult",
    "build_default_bmt_manifest",
    "ensure_plugin_api_version_supported",
    "parse_kardome_runner_json_file",
    "parse_kardome_runner_json_payload",
    "run_subprocess_in_workspace",
]

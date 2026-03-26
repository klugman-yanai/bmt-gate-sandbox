"""Stable plugin SDK surface (image-baked; see docs/bmt-python-contributor-protocol.md)."""

from __future__ import annotations

from backend.runtime.models import (
    BmtManifest,
    ExecutionConfig,
    PluginManifest,
    ProjectManifest,
    RunnerConfig,
)
from backend.runtime.sdk.compatibility import SUPPORTED_PLUGIN_API_VERSIONS, ensure_plugin_api_version_supported
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.kardome import AdaptiveKardomeExecutor
from backend.runtime.sdk.kardome_runner_json import (
    parse_kardome_runner_json_file,
    parse_kardome_runner_json_payload,
)
from backend.runtime.sdk.manifest_build import build_default_bmt_manifest
from backend.runtime.sdk.plugin import (
    PLUGIN_EXECUTE_EXCEPTION_RAW_KEY,
    BmtPlugin,
)
from backend.runtime.sdk.protocols import BmtPluginProtocol
from backend.runtime.sdk.results import (
    CaseResult,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from backend.runtime.sdk.subprocess_batch import run_subprocess_in_workspace

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

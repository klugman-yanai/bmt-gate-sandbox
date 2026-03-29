"""Stable plugin SDK surface (image-baked; see docs/contributors.md § Python plugin protocol).

Plugin authors should use :mod:`bmtplugin` (e.g. ``import bmtplugin as bmt``). The
:mod:`backend.runtime.sdk.contributor` module is the same surface for advanced imports.
"""

from __future__ import annotations

from backend.runtime.models import (
    BmtManifest,
    ExecutionConfig,
    PluginManifest,
    ProjectManifest,
    RunnerConfig,
)
from backend.runtime.sdk.baseline_verdict import (
    evaluate_baseline_tolerance_verdict,
    evaluate_pass_threshold_verdict,
)
from backend.runtime.sdk.compatibility import SUPPORTED_PLUGIN_API_VERSIONS, ensure_plugin_api_version_supported
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.gating import (
    BaselineToleranceEvaluator,
    BaselineTolerancePolicy,
    PassThresholdEvaluator,
    PassThresholdPolicy,
)
from backend.runtime.sdk.kardome import AdaptiveKardomeExecutor
from backend.runtime.sdk.kardome_runner_json import (
    parse_kardome_runner_json_file,
    parse_kardome_runner_json_payload,
)
from backend.runtime.sdk.kardome_stdout import legacy_stdout_config_from_context
from backend.runtime.sdk.manifest_build import build_default_bmt_manifest
from backend.runtime.sdk.plugin import BmtPlugin, parse_max_grace_case_failures
from backend.runtime.sdk.protocols import BmtPluginProtocol, SupportsGraceCaseLimits
from backend.runtime.sdk.results import (
    PLUGIN_EXECUTE_EXCEPTION_RAW_KEY,
    CaseArtifacts,
    CaseMetrics,
    CaseResult,
    CaseRunSummary,
    CaseStatus,
    ExecutionMode,
    ExecutionResult,
    PreparedAssets,
    ScoreResult,
    VerdictResult,
)
from backend.runtime.sdk.stage_layout import (
    SHARED_DEPENDENCIES_PREFIX,
    native_runner_uri,
    resolve_posix_under_stage,
    runner_config_native_kardome,
    shared_dependencies_dir,
)
from backend.runtime.sdk.subprocess_batch import run_subprocess_in_workspace

__all__ = [
    "PLUGIN_EXECUTE_EXCEPTION_RAW_KEY",
    "SHARED_DEPENDENCIES_PREFIX",
    "SUPPORTED_PLUGIN_API_VERSIONS",
    "AdaptiveKardomeExecutor",
    "BaselineToleranceEvaluator",
    "BaselineTolerancePolicy",
    "BmtManifest",
    "BmtPlugin",
    "BmtPluginProtocol",
    "CaseArtifacts",
    "CaseMetrics",
    "CaseResult",
    "CaseRunSummary",
    "CaseStatus",
    "ExecutionConfig",
    "ExecutionContext",
    "ExecutionMode",
    "ExecutionResult",
    "PassThresholdEvaluator",
    "PassThresholdPolicy",
    "PluginManifest",
    "PreparedAssets",
    "ProjectManifest",
    "RunnerConfig",
    "ScoreResult",
    "SupportsGraceCaseLimits",
    "VerdictResult",
    "build_default_bmt_manifest",
    "ensure_plugin_api_version_supported",
    "evaluate_baseline_tolerance_verdict",
    "evaluate_pass_threshold_verdict",
    "legacy_stdout_config_from_context",
    "native_runner_uri",
    "parse_kardome_runner_json_file",
    "parse_kardome_runner_json_payload",
    "parse_max_grace_case_failures",
    "resolve_posix_under_stage",
    "run_subprocess_in_workspace",
    "runner_config_native_kardome",
    "shared_dependencies_dir",
]

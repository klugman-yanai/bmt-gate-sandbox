"""Implementation module behind the public :mod:`bmtplugin` package (identical exports).

Prefer::

    import bmtplugin as bmt


    class MyPlugin(bmt.BmtPlugin): ...

Explicit imports only — no star-imports — so linters and type checkers stay precise.
"""

from __future__ import annotations

from backend.runtime.kardome_batch_results import KardomeBatchFile
from backend.runtime.legacy_kardome import LegacyKardomeStdoutExecutor
from backend.runtime.sdk.baseline_verdict import (
    evaluate_baseline_tolerance_verdict,
    evaluate_pass_threshold_verdict,
)
from backend.runtime.sdk.context import ExecutionContext
from backend.runtime.sdk.gating import (
    BaselineToleranceEvaluator,
    BaselineTolerancePolicy,
    PassThresholdEvaluator,
    PassThresholdPolicy,
)
from backend.runtime.sdk.kardome import AdaptiveKardomeExecutor
from backend.runtime.sdk.kardome_stdout import legacy_stdout_config_from_context
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
from backend.runtime.stdout_counter_parse import StdoutCounterParseConfig

__all__ = [
    "PLUGIN_EXECUTE_EXCEPTION_RAW_KEY",
    "SHARED_DEPENDENCIES_PREFIX",
    "AdaptiveKardomeExecutor",
    "BaselineToleranceEvaluator",
    "BaselineTolerancePolicy",
    "BmtPlugin",
    "BmtPluginProtocol",
    "CaseArtifacts",
    "CaseMetrics",
    "CaseResult",
    "CaseRunSummary",
    "CaseStatus",
    "ExecutionContext",
    "ExecutionMode",
    "ExecutionResult",
    "KardomeBatchFile",
    "LegacyKardomeStdoutExecutor",
    "PassThresholdEvaluator",
    "PassThresholdPolicy",
    "PreparedAssets",
    "ScoreResult",
    "StdoutCounterParseConfig",
    "SupportsGraceCaseLimits",
    "VerdictResult",
    "evaluate_baseline_tolerance_verdict",
    "evaluate_pass_threshold_verdict",
    "legacy_stdout_config_from_context",
    "native_runner_uri",
    "parse_max_grace_case_failures",
    "resolve_posix_under_stage",
    "run_subprocess_in_workspace",
    "runner_config_native_kardome",
    "shared_dependencies_dir",
]

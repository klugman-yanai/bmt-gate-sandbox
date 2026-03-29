"""Execution and scoring value objects.

These types are the contract between the BMT runtime, plugins, and adapters (legacy stdout,
batch JSON, etc.). Prefer constructing them via keyword arguments; use :class:`CaseMetrics` and
:class:`CaseArtifacts` instead of raw ``dict`` literals for per-case data.

:class:`CaseRunSummary` rolls up :class:`CaseResult` rows into the metrics shape expected by
:class:`~backend.runtime.sdk.gating.BaselineToleranceEvaluator`.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, RootModel, field_validator

# Key in ``ExecutionResult.raw_summary`` when :meth:`BmtPlugin.execution_failure_result` runs.
PLUGIN_EXECUTE_EXCEPTION_RAW_KEY = "plugin_execute_exception"


class CaseStatus(StrEnum):
    """Per-input outcome after runner execution."""

    OK = "ok"
    FAILED = "failed"


class ExecutionMode(StrEnum):
    """Which execution path produced an :class:`ExecutionResult`.

    Plugins and adapters should use the most specific value that applies. Unknown or
    third-party modes should extend this enum when they become stable; until then, use
    the closest documented value or propose a new member.
    """

    UNKNOWN = "unknown"
    MOCK = "mock"
    PLUGIN_DIRECT = "plugin_direct"
    KARDOME_LEGACY_STDOUT = "kardome_legacy_stdout"
    KARDOME_BATCH_JSON = "kardome_batch_json"
    ADAPTIVE_BATCH_THEN_LEGACY = "adaptive_batch_then_legacy"
    LEGACY = "legacy"
    STUB = "stub"


class CaseMetrics(RootModel[dict[str, float]]):
    """Numeric measurements for one case (e.g. ``namuh_count`` from kardome_runner output).

    Use :meth:`get` for optional keys. Keys are stable metric names; values are floats.
    """

    root: dict[str, float] = Field(default_factory=dict)

    @field_validator("root")
    @classmethod
    def _float_values(cls, v: dict[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        for k, x in v.items():
            out[str(k)] = float(x)
        return out

    def get(self, key: str, default: float = 0.0) -> float:
        raw = self.root.get(key, default)
        return float(raw) if raw is not None else default

    def __getitem__(self, key: str) -> float:
        return float(self.root[key])


class CaseArtifacts(RootModel[dict[str, str]]):
    """String paths and URIs attached to a case (log file, rendered output, etc.).

    Common keys include ``log_path`` and ``output_path`` for legacy stdout execution.
    """

    root: dict[str, str] = Field(default_factory=dict)

    @field_validator("root")
    @classmethod
    def _str_values(cls, v: dict[str, Any]) -> dict[str, str]:
        return {str(k): str(x) for k, x in v.items()}

    def get(self, key: str, default: str = "") -> str:
        return str(self.root.get(key, default))

    def __getitem__(self, key: str) -> str:
        return str(self.root[key])


class PreparedAssets(BaseModel):
    """Paths and handles resolved during :meth:`~backend.runtime.sdk.plugin.BmtPlugin.prepare`."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    dataset_root: Path = Field(description="Root directory of input audio (or dataset) for this leg.")
    workspace_root: Path = Field(description="Isolated working directory for this run (outputs, logs, temp files).")
    runner_path: Path | None = Field(
        default=None,
        description="Resolved path to the native runner binary, when configured.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional plugin-specific handles (rare; prefer explicit fields when stable).",
    )


class CaseResult(BaseModel):
    """Normalized outcome for a single benchmark input (one WAV, one batch row, etc.)."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, populate_by_name=True)

    case_id: str = Field(
        description="Stable id for this case within the leg (often dataset-relative path).",
    )
    input_path: Path = Field(description="Filesystem path to the primary input artifact.")
    exit_code: int = Field(
        description=(
            "POSIX-style exit status from the kardome_runner **subprocess** when a process ran "
            "(0 = success). Framework uses negative sentinels (e.g. -1) when no subprocess ran "
            "(timeout, log open failure, plugin-level failure before spawn)."
        ),
    )
    status: CaseStatus = Field(description="Coarse pass/fail for this case after runner + parsing.")
    metrics: CaseMetrics = Field(
        default_factory=lambda: CaseMetrics(root={}),
        description="Numeric metrics extracted from runner output (counters, scores-on-case, …).",
    )
    artifacts: CaseArtifacts = Field(
        default_factory=lambda: CaseArtifacts(root={}),
        description="String paths to logs, outputs, and other file artifacts for this case.",
    )
    runner_case_diagnostic: str = Field(
        default="",
        description=(
            "When ``status`` is failed (or ok with a warning token), explains what went wrong: "
            "kardome_runner exit reason, timeout marker, missing counter, batch JSON parse error, "
            "or framework token (e.g. ``log_open_failed:…``). Empty string when the case "
            "completed successfully with nothing to report."
        ),
        validation_alias=AliasChoices("runner_case_diagnostic", "error"),
    )

    @property
    def error(self) -> str:
        """Backward-compatible alias for :attr:`runner_case_diagnostic`."""
        return self.runner_case_diagnostic


class ExecutionResult(BaseModel):
    """Outcome of :meth:`~backend.runtime.sdk.plugin.BmtPlugin.execute` for one leg."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    execution_mode_used: ExecutionMode = Field(
        description="Adapter or code path that produced ``case_results`` (batch JSON, legacy stdout, …).",
    )
    case_results: list[CaseResult] = Field(
        description="One entry per case; may be empty only in exceptional framework paths.",
    )
    raw_summary: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Execution-level payload not folded into :class:`CaseResult` rows. Examples: the full "
            "kardome batch JSON object (``kardome_batch_json`` mode) for downstream scoring; "
            f"framework markers such as ``{PLUGIN_EXECUTE_EXCEPTION_RAW_KEY!r}`` when execute "
            "failed inside the adapter. Opaque to the coordinator; plugins may read it in "
            "``score`` / ``evaluate`` when they set it."
        ),
    )


class CaseRunSummary(BaseModel):
    """Immutable rollup of :attr:`ExecutionResult.case_results` for :class:`ScoreResult` metrics.

    Use :meth:`from_case_results` to build from execution output, then :meth:`as_score_metrics`
    for the conventional ``case_count`` / ``cases_ok`` / ``cases_failed`` keys.
    """

    model_config = ConfigDict(frozen=True)

    case_count: int = Field(ge=0, description="Total cases in the leg.")
    cases_ok: int = Field(ge=0, description="Cases with :attr:`CaseStatus.OK`.")
    cases_failed: int = Field(ge=0, description="Cases that did not reach OK.")
    cases_failed_ids: list[str] = Field(
        default_factory=list,
        description="Stable ids (usually dataset-relative paths) for failed cases.",
    )

    @field_validator("cases_failed_ids")
    @classmethod
    def _failed_ids_strings(cls, v: list[str]) -> list[str]:
        return [str(x) for x in v]

    @classmethod
    def from_case_results(cls, case_results: Sequence[CaseResult]) -> CaseRunSummary:
        failed_ids = [r.case_id for r in case_results if r.status != CaseStatus.OK]
        ok = len(case_results) - len(failed_ids)
        return cls(
            case_count=len(case_results),
            cases_ok=ok,
            cases_failed=len(failed_ids),
            cases_failed_ids=failed_ids,
        )

    def as_score_metrics(self) -> dict[str, Any]:
        """Standard keys consumed by :class:`BaselineToleranceEvaluator` and dashboards."""
        return {
            "case_count": self.case_count,
            "cases_ok": self.cases_ok,
            "cases_failed": self.cases_failed,
            "cases_failed_ids": list(self.cases_failed_ids),
        }


class ScoreResult(BaseModel):
    """Aggregate scoring output for a leg."""

    model_config = ConfigDict(frozen=True)

    aggregate_score: float = Field(description="Single number used for gating (plugin-defined scale).")
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured scoring details (case counts, outcome lists, …) for reporting.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional scoring metadata not sent to GitHub tables by default.",
    )


class VerdictResult(BaseModel):
    """Pass/fail decision for CI after scoring."""

    model_config = ConfigDict(frozen=True)

    passed: bool = Field(description="Whether this leg should gate green.")
    status: str = Field(description="Domain status string (e.g. pass / fail / error).")
    reason_code: str = Field(description="Stable machine-readable reason for the verdict.")
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Human-oriented fields for dashboards and logs.",
    )

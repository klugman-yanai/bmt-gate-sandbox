"""Typed value classes and boundary payloads for gcp/image (L1 — imports only from L0).

All identity, config, result, and boundary shapes used across the BMT framework live here.
No raw ``dict[str, Any]`` at API or internal boundaries — use these value classes instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Identity / paths (frozen value objects)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BucketPaths:
    """Resolved GCS bucket coordinates."""

    bucket_name: str
    runtime_root: str  # e.g. "gs://<bucket>" (no trailing slash)

    @property
    def root_uri(self) -> str:
        return self.runtime_root.rstrip("/")


@dataclass(frozen=True, slots=True)
class LegIdentity:
    """Unique identity for one BMT leg within a run."""

    project: str
    bmt_id: str
    run_id: str
    index: int = 0


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Local workspace directory layout for a single BMT run."""

    workspace_root: Path
    run_root: Path
    staging_dir: Path
    runtime_dir: Path
    outputs_dir: Path
    logs_dir: Path
    results_dir: Path
    archive_dir: Path
    cache_base: Path
    cache_meta_dir: Path

    @classmethod
    def from_root(cls, workspace_root: Path, cache_base: Path) -> WorkspacePaths:
        run_root = workspace_root
        return cls(
            workspace_root=workspace_root,
            run_root=run_root,
            staging_dir=run_root / "staging",
            runtime_dir=run_root / "runtime",
            outputs_dir=run_root / "outputs",
            logs_dir=run_root / "logs",
            results_dir=run_root / "results",
            archive_dir=run_root / "archive",
            cache_base=cache_base,
            cache_meta_dir=cache_base / "meta",
        )


@dataclass(frozen=True, slots=True)
class RunnerIdentity:
    """Metadata identifying the runner binary used for a BMT."""

    name: str
    build_id: str
    source_ref: str = ""


# ---------------------------------------------------------------------------
# Gate / verdict value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateResult:
    """Pure gate evaluation outcome (no GCS/orchestration deps)."""

    comparison: str
    last_score: float | None
    current_score: float
    passed: bool
    reason: str
    tolerance_abs: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison": self.comparison,
            "last_score": self.last_score,
            "current_score": self.current_score,
            "passed": self.passed,
            "reason": self.reason,
            "tolerance_abs": self.tolerance_abs,
        }


@dataclass(frozen=True, slots=True)
class GatePhaseResult:
    """Aggregated gate phase outcome (status + summary + metrics)."""

    status: str  # "pass" | "fail" | "warning"
    reason_code: str
    gate: GateResult
    aggregate_score: float
    raw_score: float
    delta_from_previous: float | None
    failed_count: int
    previous_latest: dict[str, Any] | None
    demo_force_pass: bool


# ---------------------------------------------------------------------------
# Per-file runner result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FileRunResult:
    """Per-file runner execution result.

    Project-specific fields (e.g. ``namuh_count`` for SK) are stored in ``extra``.
    """

    file: str
    exit_code: int
    status: str  # "ok" | "error" | "timeout"
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "file": self.file,
            "exit_code": self.exit_code,
            "status": self.status,
            "error": self.error,
        }
        d.update(self.extra)
        return d


# ---------------------------------------------------------------------------
# Config for managers (injected by the framework)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BmtJobGateConfig:
    """Gate section of a BMT job config."""

    comparison: str = "gte"
    tolerance_abs: float = 0.0


@dataclass(frozen=True, slots=True)
class BmtJobParsingConfig:
    """Per-BMT parsing config (project-specific runner output)."""

    keyword: str = ""
    counter_pattern: str = ""


@dataclass(frozen=True, slots=True)
class BmtJobPathsConfig:
    """Paths section of a BMT job config."""

    dataset_prefix: str = ""
    results_prefix: str = ""
    outputs_prefix: str = ""
    logs_prefix: str = ""


@dataclass(frozen=True, slots=True)
class BmtJobRunnerConfig:
    """Runner section of a BMT job config."""

    uri: str = ""
    deps_prefix: str = ""


@dataclass(frozen=True, slots=True)
class BmtJobCacheConfig:
    """Cache section of a BMT job runtime config."""

    enabled: bool = True
    root: str = ""
    dataset_ttl_sec: int = 300


@dataclass(frozen=True, slots=True)
class BmtJobRuntimeConfig:
    """Runtime section of a BMT job config."""

    num_source_test: int = 0
    enable_overrides: dict[str, Any] = field(default_factory=dict)
    cache: BmtJobCacheConfig = field(default_factory=BmtJobCacheConfig)


@dataclass(frozen=True, slots=True)
class BmtJobConfig:
    """Single BMT definition within a project's bmt_jobs.json."""

    enabled: bool = True
    runner: BmtJobRunnerConfig = field(default_factory=BmtJobRunnerConfig)
    template_uri: str = ""
    paths: BmtJobPathsConfig = field(default_factory=BmtJobPathsConfig)
    runtime: BmtJobRuntimeConfig = field(default_factory=BmtJobRuntimeConfig)
    gate: BmtJobGateConfig = field(default_factory=BmtJobGateConfig)
    parsing: BmtJobParsingConfig = field(default_factory=BmtJobParsingConfig)
    input_file_extensions: list[str] = field(default_factory=lambda: ["*.wav"])
    warning_policy: dict[str, Any] = field(default_factory=dict)
    demo: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BmtJobConfig:
        runner_raw = data.get("runner") or {}
        paths_raw = data.get("paths") or {}
        runtime_raw = data.get("runtime") or {}
        cache_raw = runtime_raw.get("cache") or {} if isinstance(runtime_raw, dict) else {}
        gate_raw = data.get("gate") or {}
        parsing_raw = data.get("parsing") or {}
        return cls(
            enabled=data.get("enabled", True) is not False,
            runner=BmtJobRunnerConfig(
                uri=str(runner_raw.get("uri", "")),
                deps_prefix=str(runner_raw.get("deps_prefix", "")),
            ),
            template_uri=str(data.get("template_uri", "")),
            paths=BmtJobPathsConfig(
                dataset_prefix=str(paths_raw.get("dataset_prefix", "")),
                results_prefix=str(paths_raw.get("results_prefix", "")),
                outputs_prefix=str(paths_raw.get("outputs_prefix", "")),
                logs_prefix=str(paths_raw.get("logs_prefix", "")),
            ),
            runtime=BmtJobRuntimeConfig(
                num_source_test=int(runtime_raw.get("num_source_test", 0)) if isinstance(runtime_raw, dict) else 0,
                enable_overrides=(
                    dict(runtime_raw.get("enable_overrides", {})) if isinstance(runtime_raw, dict) else {}
                ),
                cache=BmtJobCacheConfig(
                    enabled=cache_raw.get("enabled", True) is not False,
                    root=str(cache_raw.get("root", "")),
                    dataset_ttl_sec=int(cache_raw.get("dataset_ttl_sec", 300)),
                ),
            ),
            gate=BmtJobGateConfig(
                comparison=str(gate_raw.get("comparison", "gte")),
                tolerance_abs=float(gate_raw.get("tolerance_abs", 0.0) or 0.0),
            ),
            parsing=BmtJobParsingConfig(
                keyword=str(parsing_raw.get("keyword", "")),
                counter_pattern=str(parsing_raw.get("counter_pattern", "")),
            ),
            input_file_extensions=data.get("input_file_extensions") or ["*.wav"],
            warning_policy=data.get("warning_policy") or {},
            demo=data.get("demo") or {},
            artifacts=data.get("artifacts") or {},
        )


@dataclass(frozen=True, slots=True)
class BmtJobsConfig:
    """Top-level bmt_jobs.json: maps bmt_id -> BmtJobConfig."""

    bmts: dict[str, BmtJobConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BmtJobsConfig:
        raw_bmts = data.get("bmts") or {}
        if not isinstance(raw_bmts, dict):
            return cls(bmts={})
        return cls(
            bmts={k: BmtJobConfig.from_dict(v) if isinstance(v, dict) else BmtJobConfig() for k, v in raw_bmts.items()}
        )


@dataclass(frozen=True, slots=True)
class ManagerConfig:
    """Config injected into a BMT manager by the framework. Contributors receive this, not raw dicts."""

    leg_identity: LegIdentity
    bucket_paths: BucketPaths
    jobs_config: BmtJobConfig
    workspace_paths: WorkspacePaths
    run_context: str = "manual"
    limit: int = 0
    max_jobs: int = 4
    human: bool = False
    summary_out: Path = Path("manager_summary.json")


# ---------------------------------------------------------------------------
# Registry (project -> manager mapping, loaded from GCS at runtime)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BmtProjectEntry:
    """One project's entry in the BMT registry (bmt_projects.json)."""

    manager_script: str
    jobs_config: str


@dataclass(frozen=True, slots=True)
class BmtRegistry:
    """Project registry loaded from GCS at runtime."""

    projects: dict[str, BmtProjectEntry] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BmtRegistry:
        projects: dict[str, BmtProjectEntry] = {}
        for k, v in (data or {}).items():
            if isinstance(v, dict):
                projects[k] = BmtProjectEntry(
                    manager_script=str(v.get("manager_script", "")),
                    jobs_config=str(v.get("jobs_config", "")),
                )
        return cls(projects=projects)

    def with_project(self, name: str, entry: BmtProjectEntry) -> BmtRegistry:
        updated = dict(self.projects)
        updated[name] = entry
        return BmtRegistry(projects=updated)


# ---------------------------------------------------------------------------
# Boundary payloads (TypedDict — typed shapes for JSON at boundaries)
# ---------------------------------------------------------------------------


class TriggerLeg(TypedDict, total=False):
    """One leg inside a run trigger payload."""

    project: str
    bmt_id: str
    run_id: str
    request_scope: str


class TriggerPayload(TypedDict, total=False):
    """Run trigger JSON written to GCS by CI."""

    legs: list[TriggerLeg]
    repository: str
    sha: str
    ref: str
    workflow_run_id: str
    run_context: str
    bucket: str
    triggered_at: str
    status_context: str
    runtime_status_context: str
    pull_request_number: int | None


class AckPayload(TypedDict, total=False):
    """Handshake ack JSON written to GCS by the VM watcher."""

    workflow_run_id: str
    acked_at: str
    instance: str
    status: str


class StatusPayload(TypedDict, total=False):
    """Status/heartbeat JSON written to GCS by the VM watcher."""

    workflow_run_id: str
    vm_state: str
    legs: list[dict[str, Any]]
    elapsed_sec: int
    eta_sec: int | None
    current_leg: dict[str, Any] | None
    updated_at: str


class LegSummary(TypedDict, total=False):
    """Per-leg summary from the manager (manager_summary.json shape)."""

    timestamp: str
    project_id: str
    bmt_id: str
    run_context: str
    run_id: str
    status: str
    reason_code: str
    demo_force_pass: bool
    passed: bool
    reason: str | None
    aggregate_score: float
    raw_aggregate_score: float
    last_score: float | None
    gate: dict[str, Any]
    delta_from_previous: float | None
    failed_count: int
    latest_json: str
    ci_verdict_uri: str
    cache_stats: dict[str, Any]
    sync_stats: dict[str, Any]
    artifact_upload_stats: dict[str, Any]
    orchestration_timing: dict[str, Any]


class CiVerdict(TypedDict, total=False):
    """Per-run CI verdict (ci_verdict.json shape)."""

    schema_version: int
    run_id: str
    project_id: str
    bmt_id: str
    status: str
    reason_code: str
    aggregate_score: float
    runner: dict[str, str]
    gate: dict[str, Any]
    timestamps: dict[str, str]
    artifacts: dict[str, str]


class CurrentPointer(TypedDict):
    """Pointer at {results_prefix}/current.json."""

    latest: str
    last_passing: str | None
    updated_at: str


class ManagerSummary(TypedDict, total=False):
    """Root orchestrator summary (bmt_root_results.json shape)."""

    schema_version: int
    project: str
    bmt_id: str
    run_id: str
    status: str
    manager_summary_path: str
    ci_verdict_uri: str
    passed: bool
    aggregate_score: float
    error: str

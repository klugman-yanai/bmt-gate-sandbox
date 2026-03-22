"""Boundary models for the modern BMT framework."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from gcp.image.config.value_types import ResultsPath, as_results_path


def _coerce_results_path(v: Any) -> ResultsPath:
    if isinstance(v, str):
        return as_results_path(v)
    raise TypeError(f"results_path must be str, got {type(v).__name__}")


ResultsPathField = Annotated[ResultsPath, BeforeValidator(_coerce_results_path)]


class PluginManifest(BaseModel):
    api_version: str = "v1"
    plugin_name: str
    entrypoint: str
    package_root: str = "src"


class ProjectManifest(BaseModel):
    schema_version: int = 1
    project: str
    default_plugin: str = "default"
    description: str = ""


class RunnerConfig(BaseModel):
    uri: str = ""
    deps_prefix: str = ""
    template_path: str = "gcp/image/runtime/assets/kardome_input_template.json"


class ExecutionConfig(BaseModel):
    policy: str = "adaptive_batch_then_legacy"
    profile: str = "standard"


class BmtManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = 1
    project: str
    bmt_slug: str
    bmt_id: str
    enabled: bool = False
    plugin_ref: str
    inputs_prefix: str
    results_path: ResultsPathField = Field(
        validation_alias="results_prefix",
        serialization_alias="results_prefix",
    )
    outputs_prefix: str
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    plugin_config: dict[str, Any] = Field(default_factory=dict)


class WorkflowRequest(BaseModel):
    workflow_run_id: str
    repository: str = ""
    head_sha: str = ""
    head_branch: str = ""
    head_event: str = "push"
    pr_number: str = ""
    run_context: str = "ci"
    accepted_projects: list[str] = Field(default_factory=list)
    status_context: str = "BMT Gate"
    use_mock_runner: bool = False


class PlanLeg(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project: str
    bmt_slug: str
    bmt_id: str
    run_id: str
    execution_profile: str = "standard"
    manifest_path: str
    manifest_digest: str
    plugin_ref: str
    plugin_digest: str
    inputs_prefix: str
    results_path: ResultsPathField = Field(
        validation_alias="results_prefix",
        serialization_alias="results_prefix",
    )
    outputs_prefix: str


class ExecutionPlan(BaseModel):
    workflow_run_id: str
    repository: str = ""
    head_sha: str = ""
    head_branch: str = ""
    head_event: str = "push"
    pr_number: str = ""
    run_context: str = "ci"
    accepted_projects: list[str] = Field(default_factory=list)
    status_context: str = "BMT Gate"
    use_mock_runner: bool = False
    standard_task_count: int = 0
    heavy_task_count: int = 0
    legs: list[PlanLeg]


class ReportingMetadata(BaseModel):
    workflow_execution_name: str = ""
    workflow_execution_url: str = ""
    check_run_id: int | None = None
    started_at: str = ""


class ProgressRecord(BaseModel):
    project: str
    bmt_slug: str
    status: str
    started_at: str
    updated_at: str
    duration_sec: int | None = None
    reason_code: str = ""


class ScorePayload(BaseModel):
    aggregate_score: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class LegSummary(BaseModel):
    project: str
    bmt_slug: str
    bmt_id: str
    run_id: str
    status: str
    reason_code: str
    plugin_ref: str
    execution_mode_used: str
    score: ScorePayload
    verdict_summary: dict[str, Any] = Field(default_factory=dict)
    latest_uri: str = ""
    ci_verdict_uri: str = ""
    summary_uri: str = ""
    logs_uri: str = ""
    duration_sec: int | None = None


@dataclass(frozen=True, slots=True)
class StageRuntimePaths:
    stage_root: Path
    workspace_root: Path

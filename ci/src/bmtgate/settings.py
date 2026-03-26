"""Typed CI config and context for the direct-Workflow Cloud Run handoff."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from bmtgate.contract.constants import (
    DEFAULT_CLOUD_RUN_REGION,
    ENV_BMT_CONTROL_JOB,
    ENV_BMT_STATUS_CONTEXT,
    ENV_BMT_TASK_HEAVY_JOB,
    ENV_BMT_TASK_STANDARD_JOB,
    ENV_CLOUD_RUN_REGION,
    ENV_GCP_PROJECT,
    ENV_GCP_SA_EMAIL,
    ENV_GCP_WIF_PROVIDER,
    ENV_GCS_BUCKET,
    STATUS_CONTEXT,
)

__all__ = [
    "BmtConfig",
    "BmtContext",
    "WorkflowContext",
    "context_from_env",
    "get_config",
    "get_context",
    "get_context_path",
    "load_context_from_file",
    "load_env",
    "workflow_context_env_keys",
    "workflow_field_to_env_var",
    "write_context_to_file",
]

DEFAULT_CONTEXT_FILE = ".bmt/context.json"
_RUNTIME_ENV_KEYS = frozenset(
    {
        ENV_GCS_BUCKET,
        ENV_GCP_PROJECT,
        ENV_GCP_SA_EMAIL,
        ENV_GCP_WIF_PROVIDER,
        ENV_CLOUD_RUN_REGION,
        ENV_BMT_CONTROL_JOB,
        ENV_BMT_TASK_STANDARD_JOB,
        ENV_BMT_TASK_HEAVY_JOB,
        ENV_BMT_STATUS_CONTEXT,
    }
)


def workflow_field_to_env_var(field_name: str) -> str:
    """Map :class:`WorkflowContext` field name to GitHub Actions env var (UPPER_SNAKE)."""
    return "_".join(part.upper() for part in field_name.split("_"))


def workflow_context_env_keys() -> frozenset[str]:
    """Env vars that populate :class:`WorkflowContext` — derived from the model (SSOT)."""
    return frozenset(workflow_field_to_env_var(name) for name in WorkflowContext.model_fields)


class BmtConfig(BaseSettings):
    """CI/GCP config loaded from environment (and optional .env)."""

    model_config = SettingsConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        validate_default=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    gcs_bucket: str = Field("", validation_alias=ENV_GCS_BUCKET)
    gcp_project: str = Field("", validation_alias=ENV_GCP_PROJECT)
    gcp_sa_email: str = Field("", validation_alias=ENV_GCP_SA_EMAIL)
    gcp_wif_provider: str = Field("", validation_alias=ENV_GCP_WIF_PROVIDER)
    cloud_run_region: str = Field(DEFAULT_CLOUD_RUN_REGION, validation_alias=ENV_CLOUD_RUN_REGION)
    # Cloud Run job names — used by local dev tooling (e.g. bucket_upload_dataset).
    bmt_control_job: str = Field("", validation_alias=ENV_BMT_CONTROL_JOB)
    bmt_task_standard_job: str = Field("", validation_alias=ENV_BMT_TASK_STANDARD_JOB)
    bmt_task_heavy_job: str = Field("", validation_alias=ENV_BMT_TASK_HEAVY_JOB)
    bmt_status_context: str = Field(STATUS_CONTEXT, validation_alias=ENV_BMT_STATUS_CONTEXT)
    bmt_progress_description: str = "Dispatching Cloud Run BMT pipeline..."
    bmt_failure_status_description: str = "Cloud Run BMT dispatch failed."

    def require_gcp(self) -> None:
        """Require GCP and WIF vars; handoff needs them for OIDC auth and bucket access."""
        for field_name in ("gcs_bucket", "gcp_project", "gcp_sa_email", "gcp_wif_provider"):
            if not getattr(self, field_name).strip():
                raise RuntimeError(f"Required config {field_name!r} is not set or empty")


class WorkflowContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    accepted: str | None = None
    accepted_projects: str | None = None
    available_artifacts: str | None = None
    bmt_runners_preseeded_in_gcs: str | None = None
    bmt_skip_publish_runners: str | None = None
    dispatch_head_sha: str | None = None
    dispatch_pr_number: str | None = None
    failure_reason: str | None = None
    filtered_matrix: str | None = None
    github_repository: str | None = None
    github_run_id: str | None = None
    github_server_url: str | None = None
    handshake_ok: str | None = None
    head_branch: str | None = None
    head_sha: str | None = None
    mode: str | None = None
    orch_handshake_ok: str | None = None
    orch_has_legs: str | None = None
    prepare_head_sha: str | None = None
    prepare_pr_number: str | None = None
    prepare_result: str | None = None
    pr_number: str | None = None
    repository: str | None = None
    runner_matrix: str | None = None
    skip_missing_runner_artifacts: str | None = None
    target_url: str | None = None


class BmtContext(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    config: BmtConfig = Field(default_factory=BmtConfig)
    workflow: WorkflowContext | None = None


def get_config(runtime: Mapping[str, str] | None = None) -> BmtConfig:
    """Load BmtConfig from env (and optional .env), or from a provided mapping (e.g. tests)."""
    if runtime is not None:
        env = dict(runtime)
        return BmtConfig.model_validate(
            {
                key.lower(): str(env[key]).strip()
                for key in _RUNTIME_ENV_KEYS
                if str(env.get(key, "")).strip()
            }
        )
    return BmtConfig()


def get_context_path(runtime: Mapping[str, str] | None = None) -> Path:
    env = dict(runtime) if runtime is not None else dict(os.environ)
    raw = str(env.get("BMT_CONTEXT_FILE", "")).strip()
    return Path(raw) if raw else Path(DEFAULT_CONTEXT_FILE)


def context_from_env(runtime: Mapping[str, str] | None = None) -> BmtContext:
    env = dict(runtime) if runtime is not None else dict(os.environ)
    workflow_data = {
        env_key.lower(): str(env[env_key]).strip()
        for env_key in workflow_context_env_keys()
        if str(env.get(env_key, "")).strip()
    }
    workflow = WorkflowContext.model_validate(workflow_data) if workflow_data else None
    return BmtContext(config=get_config(env), workflow=workflow)


def load_context_from_file(path: Path | str) -> BmtContext | None:
    context_path = Path(path)
    if not context_path.is_file():
        return None
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return BmtContext.model_validate(payload)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid BMT context file {context_path}: {exc}") from exc


def write_context_to_file(path: Path | str, context: BmtContext) -> None:
    context_path = Path(path)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(context.model_dump_json(indent=2), encoding="utf-8")


def get_context() -> BmtContext | None:
    return load_context_from_file(get_context_path(runtime=dict(os.environ)))


def _github_env_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\n", "%0A")


def load_env() -> None:
    github_env = (os.environ.get("GITHUB_ENV") or "").strip()
    if not github_env:
        raise RuntimeError("GITHUB_ENV is not set (not running in a GitHub Actions step?)")
    config = get_config()
    with open(github_env, "a", encoding="utf-8") as handle:
        for name in BmtConfig.model_fields:
            handle.write(f"{name.upper()}={_github_env_escape(str(getattr(config, name)))}\n")

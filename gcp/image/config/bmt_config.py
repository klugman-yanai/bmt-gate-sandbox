"""Single source of truth for BMT config: Pydantic model with field defaults; runtime injection only (no JSON, no env overrides).

This module defines:
- **Behavioral constants** (top-level) — fixed product behavior; not overridable via env.
- **RuntimeEnvKey whitelist** — the only env keys that may inject into BmtConfig (no other env is read).
- **BmtConfig** — schema and default values. get_config(runtime=...) builds a config from whitelisted env;
  any key not set in runtime keeps the model default.

Actual values in CI typically come from GitHub repo variables (set e.g. by `just terraform-export-vars-apply`
from Terraform outputs). Terraform declares *what* to set; this module defines *how* it is read and what
defaults apply when env is missing. Supports optional context file (.bmt/context.json) for config +
workflow step outputs to avoid env vars in CLI.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from gcp.image.config import constants

DEFAULT_GCP_ZONE: Final[str] = constants.DEFAULT_GCP_ZONE

# ---------------------------------------------------------------------------
# Behavioral constants (not config; fixed product behavior)
# ---------------------------------------------------------------------------
DEFAULT_REPO_ROOT: Final[str] = constants.DEFAULT_REPO_ROOT
DEFAULT_RUNTIME_CONTEXT: Final[str] = "BMT Runtime"
TRIGGER_METADATA_KEEP_RECENT: Final[int] = 2
VM_STABILIZATION_SEC: Final[int] = 45
VM_START_RECOVERY_ATTEMPTS: Final[int] = 2
VM_RECOVERY_START_DELAY_SEC: Final[int] = 10
PREEMPT_ON_PR_STALE_QUEUE: Final[bool] = True
STALE_TRIGGER_AGE_HOURS: Final[int] = 2
VM_START_TIMEOUT_SEC: Final[int] = 420
IDLE_TIMEOUT_SEC: Final[int] = 600
TRIGGER_STALE_SEC: Final[int] = 900
# VM stop: wait for TERMINATED after issuing stop (e.g. select-available-vm).
VM_STOP_WAIT_TIMEOUT_SEC: Final[int] = 420

# Context file: single file for config + workflow step outputs (avoids env vars in CLI).
DEFAULT_CONTEXT_FILE: Final[str] = ".bmt/context.json"

# Only these env keys are injected into config. All other values are defaults or derived
# in code — no env override for zone, subscription, topic, status context,
# or handshake/description constants (so users cannot break things by setting them).
# BMT_REPO_ROOT is set by VM metadata or startup script; run_watcher and tests depend on it.
RuntimeEnvKey = Literal[
    "GCS_BUCKET",
    "GCP_PROJECT",
    "GCP_SA_EMAIL",
    "BMT_LIVE_VM",
    "BMT_REPO_ROOT",
    "GCP_WIF_PROVIDER",
]

_RUNTIME_KEYS: Final[frozenset[RuntimeEnvKey]] = frozenset({
    "GCS_BUCKET",
    "GCP_PROJECT",
    "GCP_SA_EMAIL",
    "BMT_LIVE_VM",
    "BMT_REPO_ROOT",
    "GCP_WIF_PROVIDER",
})

# Type aliases for constrained numeric config (self-documenting and validated)
TimeoutSec = Annotated[int, Field(ge=0, le=86400, description="Timeout in seconds (0-86400)")]
HandshakeTimeoutSec = Annotated[int, Field(ge=1, le=3600, description="Handshake wait 1-3600s")]

# Required BMT config field names for GCP operations (must be non-empty when calling require_gcp).
_REQUIRED_GCP_FIELDS: Final[tuple[str, ...]] = (
    "gcs_bucket",
    "gcp_project",
    "gcp_zone",
    "gcp_sa_email",
    "bmt_vm_name",
)


class BmtConfig(BaseModel):
    """BMT config: defaults in code; required/runtime fields from injection whitelist only."""

    model_config = ConfigDict(
        extra="forbid",
        validate_default=True,
        str_strip_whitespace=True,
    )

    # Required (injected from runtime whitelist only)
    gcs_bucket: str = Field(default="", description="GCS bucket name")
    gcp_project: str = Field(default="", description="GCP project ID")
    gcp_zone: str = Field(
        default=DEFAULT_GCP_ZONE,
        description="GCP zone (europe-west4 only; not a repo var)",
    )
    gcp_sa_email: str = Field(default="", description="Service account email")
    bmt_vm_name: str = Field(default="", description="BMT VM instance name")
    bmt_repo_root: str = Field(default="", description="Repo root on VM (overrides default)")
    # Optional runtime (whitelist; may be empty)
    gcp_wif_provider: str = Field(default="", description="Workload Identity Federation provider")
    bmt_pubsub_topic: str = Field(
        default=constants.PUBSUB_TOPIC_NAME,
        description="Pub/Sub topic for trigger notifications",
    )
    bmt_pubsub_subscription: str = Field(default="", description="Pub/Sub subscription (empty => derived from bmt_vm_name)")
    # Defaults (code only; no JSON, no env overlay)
    bmt_status_context: str = Field(
        default=constants.STATUS_CONTEXT,
        description="GitHub status check context name",
    )
    bmt_handshake_timeout_sec: HandshakeTimeoutSec = Field(default=420, description="VM handshake wait (s)")
    bmt_handshake_timeout_sec_reuse_running: HandshakeTimeoutSec = Field(
        default=600,
        description="VM handshake wait when reusing a RUNNING VM (s)",
    )
    bmt_progress_description: str = Field(
        default="BMT in progress…",
        description="Commit status description while BMT is in progress",
    )
    bmt_failure_status_description: str = Field(
        default="BMT cancelled: VM handshake timeout before pickup.",
        description="Commit status description on handshake timeout failure",
    )

    def require_gcp(self) -> None:
        """Raise if any required GCP/BMT field is empty. Call when GCP ops are needed."""
        for name in _REQUIRED_GCP_FIELDS:
            val = getattr(self, name)
            if not (val and str(val).strip()):
                raise RuntimeError(f"Required config {name!r} is not set or empty")

    @property
    def effective_repo_root(self) -> str:
        """Repo root: injected bmt_repo_root or default (declarative default, not a repo var)."""
        return (self.bmt_repo_root or "").strip() or DEFAULT_REPO_ROOT

    @property
    def effective_pubsub_subscription(self) -> str:
        """Pub/Sub subscription: injected or derived from VM name (bmt-vm-<bmt_vm_name>)."""
        sub = (self.bmt_pubsub_subscription or "").strip()
        if sub:
            return sub
        if self.bmt_vm_name and str(self.bmt_vm_name).strip():
            return "bmt-vm-" + str(self.bmt_vm_name).strip()
        return ""


# ---------------------------------------------------------------------------
# Context file (config + workflow step outputs)
# ---------------------------------------------------------------------------

# Env keys written to context.workflow by write-context (step outputs / job inputs).
WORKFLOW_CONTEXT_ENV_KEYS: Final[tuple[str, ...]] = (
    "VM_REUSED_RUNNING",
    "RESTART_VM",
    "STALE_CLEANUP_COUNT",
    "SELECTED_VM",
    "REPOSITORY",
    "GITHUB_REPOSITORY",
    "HEAD_SHA",
    "HEAD_BRANCH",
    "PR_NUMBER",
    "MODE",
    "TRIGGER_WRITTEN",
    "VM_STARTED",
    "HANDSHAKE_OK",
    "HANDSHAKE_ELAPSED_SEC",
    "HANDOFF_STATE_LINE",
    "FAILURE_REASON",
    "GITHUB_SERVER_URL",
    "GITHUB_RUN_ID",
    "TARGET_URL",
    "PREPARE_RESULT",
    "PREPARE_HEAD_SHA",
    "DISPATCH_HEAD_SHA",
    "PREPARE_PR_NUMBER",
    "DISPATCH_PR_NUMBER",
    "ORCH_HAS_LEGS",
    "ORCH_HANDSHAKE_OK",
    "ORCH_TRIGGER_WRITTEN",
    "RUNNER_MATRIX",
    "AVAILABLE_ARTIFACTS",
    "BMT_RUNNERS_PRESEEDED_IN_GCS",
    "ACCEPTED",
    "FILTERED_MATRIX",
)


class WorkflowContext(BaseModel):
    """Workflow step outputs and job inputs; all optional. Populated from env by write-context."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    vm_reused_running: str | None = None
    restart_vm: str | None = None
    stale_cleanup_count: str | None = None
    selected_vm: str | None = None
    repository: str | None = None
    github_repository: str | None = None
    head_sha: str | None = None
    head_branch: str | None = None
    pr_number: str | None = None
    mode: str | None = None
    trigger_written: str | None = None
    vm_started: str | None = None
    handshake_ok: str | None = None
    handshake_elapsed_sec: str | None = None
    handoff_state_line: str | None = None
    failure_reason: str | None = None
    github_server_url: str | None = None
    github_run_id: str | None = None
    target_url: str | None = None
    prepare_result: str | None = None
    prepare_head_sha: str | None = None
    dispatch_head_sha: str | None = None
    prepare_pr_number: str | None = None
    dispatch_pr_number: str | None = None
    orch_has_legs: str | None = None
    orch_handshake_ok: str | None = None
    orch_trigger_written: str | None = None
    runner_matrix: str | None = None
    available_artifacts: str | None = None
    bmt_runners_preseeded_in_gcs: str | None = None
    accepted: str | None = None
    filtered_matrix: str | None = None


class BmtContext(BaseModel):
    """Full runtime context: config + optional workflow step outputs. Serialized to .bmt/context.json."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    config: BmtConfig = Field(default_factory=BmtConfig)
    workflow: WorkflowContext | None = Field(default=None, description="Step outputs / job inputs")


def _env_key_to_workflow_field(env_key: str) -> str:
    """Map env key to WorkflowContext field name (lowercase, underscores)."""
    return env_key.lower()


def context_from_env(runtime: Mapping[str, str] | None = None) -> BmtContext:
    """Build BmtContext from env: config from whitelist, workflow from WORKFLOW_CONTEXT_ENV_KEYS."""
    env: Mapping[str, str] = dict(runtime) if runtime is not None else dict(os.environ)
    config = get_config(runtime=env)
    workflow_data: dict[str, str] = {}
    for env_key in WORKFLOW_CONTEXT_ENV_KEYS:
        if env_key in env and str(env.get(env_key, "")).strip():
            field_name = _env_key_to_workflow_field(env_key)
            workflow_data[field_name] = str(env[env_key]).strip()
    workflow = WorkflowContext.model_validate(workflow_data) if workflow_data else None
    return BmtContext(config=config, workflow=workflow)


def load_context_from_file(path: Path | str) -> BmtContext | None:
    """Load BmtContext from a JSON file. Returns None if file missing or invalid."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return BmtContext.model_validate(data)
    except Exception:
        return None


def write_context_to_file(path: Path | str, context: BmtContext) -> None:
    """Write BmtContext to a JSON file. Parent directory created if needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(context.model_dump_json(indent=2), encoding="utf-8")


def get_context_path(runtime: Mapping[str, str] | None = None) -> Path:
    """Return path for context file: default .bmt/context.json (cwd-relative)."""
    env: Mapping[str, str] = dict(runtime) if runtime is not None else dict(os.environ)
    raw = (env.get("BMT_CONTEXT_FILE") or "").strip()
    return Path(raw) if raw else Path(DEFAULT_CONTEXT_FILE)


# Env key -> model field name (when different from env_key.lower())
_ENV_KEY_TO_CONFIG_FIELD: Final[dict[str, str]] = {"BMT_LIVE_VM": "bmt_vm_name"}


def get_config(runtime: Mapping[str, str] | None = None) -> BmtConfig:
    """Build config from model defaults + whitelisted runtime keys only. No JSON, no env overlay for defaults."""
    env: Mapping[str, str] = dict(runtime) if runtime is not None else dict(os.environ)
    runtime_data: dict[str, str | int] = {}
    for env_key in _RUNTIME_KEYS:
        if env_key in env and str(env.get(env_key, "")).strip():
            key = _ENV_KEY_TO_CONFIG_FIELD.get(env_key, env_key.lower())
            raw = str(env[env_key]).strip()
            runtime_data[key] = raw
    # Pydantic will coerce str to int for numeric fields; strip handled by model_config
    return BmtConfig.model_validate(runtime_data)


def load_bmt_config(
    config_path: str | Path | None = None,  # noqa: ARG001
    env: Mapping[str, str] | None = None,
) -> BmtConfig:
    """Load config (for compatibility). Ignores config_path; env used as runtime."""
    return get_config(runtime=env)


def reset_config_cache() -> None:
    """No-op; kept for API compatibility with tests."""

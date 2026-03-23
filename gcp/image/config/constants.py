"""Shared constants for the Cloud Run BMT runtime."""

from __future__ import annotations

from gcp.image.config.decisions import GateDecision, ReasonCode

HTTP_TIMEOUT = 30
GITHUB_API_VERSION = "2022-11-28"
EXECUTABLE_MODE = 0o111

# GitHub status context used by the coordinator.
STATUS_CONTEXT = "BMT Gate"

# GCP zone: used at runtime (not overridable via env). Terraform still requires gcp_zone in
# bmt.tfvars.json (no default there); this constant is the single value used by code/CI.
DEFAULT_GCP_ZONE = "europe-west4-a"

# Image build / policy defaults (single source; Terraform image_family default must match DEFAULT_IMAGE_FAMILY).
DEFAULT_IMAGE_FAMILY = "bmt-runtime"
DEFAULT_BASE_IMAGE_FAMILY = "ubuntu-2204-lts"
DEFAULT_BASE_IMAGE_PROJECT = "ubuntu-os-cloud"

# Cloud Run Workflow resource name — baked into infra (Pulumi); not a developer-configurable value.
DEFAULT_WORKFLOW_NAME = "bmt-workflow"

# Default Cloud Run region — override via CLOUD_RUN_REGION env var.
DEFAULT_CLOUD_RUN_REGION = "europe-west4"

# GitHub App JWT timing
JWT_CLOCK_SKEW_SEC = 60  # iat: issued 60s in the past for clock skew tolerance
JWT_LIFETIME_SEC = 600  # exp: token valid for 10 minutes

# ---------------------------------------------------------------------------
# Result path constants (filenames and segments under ResultsPath)
# ---------------------------------------------------------------------------
# Canonical JSON filenames under {results_path}/snapshots/{run_id}/ (JSON key remains results_prefix).
CURRENT_JSON = "current.json"
LATEST_JSON = "latest.json"
CI_VERDICT_JSON = "ci_verdict.json"
MANAGER_SUMMARY_JSON = "manager_summary.json"

# Directory segments under results path (see value_types.ResultsPath)
SNAPSHOTS_PREFIX = "snapshots"
LOGS_PREFIX = "logs"

# Pointer keys inside current.json
POINTER_KEY_LATEST = "latest"
POINTER_KEY_LAST_PASSING = "last_passing"

LOG_DUMPS_PREFIX = "log-dumps"

# ---------------------------------------------------------------------------
# Gate decisions & reason codes (string values = GateDecision / ReasonCode enums)
# ---------------------------------------------------------------------------
DECISION_ACCEPTED: str = GateDecision.ACCEPTED.value
DECISION_ACCEPTED_WITH_WARNINGS: str = GateDecision.ACCEPTED_WITH_WARNINGS.value
DECISION_REJECTED: str = GateDecision.REJECTED.value
DECISION_TIMEOUT: str = GateDecision.TIMEOUT.value

REASON_JOBS_SCHEMA_INVALID: str = ReasonCode.JOBS_SCHEMA_INVALID.value
REASON_BMT_NOT_DEFINED: str = ReasonCode.BMT_NOT_DEFINED.value
REASON_BMT_DISABLED: str = ReasonCode.BMT_DISABLED.value
REASON_SUPERSEDED: str = ReasonCode.SUPERSEDED.value
REASON_RUNNER_FAILURES: str = ReasonCode.RUNNER_FAILURES.value
REASON_RUNNER_TIMEOUT: str = ReasonCode.RUNNER_TIMEOUT.value
REASON_DEMO_FORCE_PASS: str = ReasonCode.DEMO_FORCE_PASS.value

# ---------------------------------------------------------------------------
# Artifact schema versioning
# ---------------------------------------------------------------------------
# Bump when adding fields (additive/non-breaking). Consumers ignore unknown keys.
ARTIFACT_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Cloud Run / FUSE constants
# ---------------------------------------------------------------------------
FUSE_MOUNT_ROOT = "/mnt/runtime"

# Summary artifacts written by each Cloud Run task for the coordinator
TRIGGER_SUMMARIES_PREFIX = "triggers/summaries"

# Partial failure reason (coordinator could not collect all leg summaries)
REASON_PARTIAL_MISSING: str = ReasonCode.PARTIAL_MISSING.value

# Cloud Run task index env var (set automatically by Cloud Run)
CLOUD_RUN_TASK_INDEX_ENV = "CLOUD_RUN_TASK_INDEX"
CLOUD_RUN_TASK_COUNT_ENV = "CLOUD_RUN_TASK_COUNT"

# Env vars set by the Workflow when invoking the Cloud Run Job
BMT_WORKFLOW_RUN_ID_ENV = "BMT_WORKFLOW_RUN_ID"

# ---------------------------------------------------------------------------
# Environment / repo variable names (single source of truth; used by CI and tools)
# ---------------------------------------------------------------------------
ENV_GCS_BUCKET = "GCS_BUCKET"
ENV_GCP_PROJECT = "GCP_PROJECT"
ENV_GCP_SA_EMAIL = "GCP_SA_EMAIL"
ENV_GCP_WIF_PROVIDER = "GCP_WIF_PROVIDER"
ENV_GCP_ZONE = "GCP_ZONE"
ENV_CLOUD_RUN_REGION = "CLOUD_RUN_REGION"
ENV_BMT_CONTROL_JOB = "BMT_CONTROL_JOB"
ENV_BMT_TASK_STANDARD_JOB = "BMT_TASK_STANDARD_JOB"
ENV_BMT_TASK_HEAVY_JOB = "BMT_TASK_HEAVY_JOB"
ENV_BMT_STATUS_CONTEXT = "BMT_STATUS_CONTEXT"
ENV_BMT_WORKFLOW_EXECUTION_URL = "BMT_WORKFLOW_EXECUTION_URL"
ENV_BMT_FAILURE_REASON = "BMT_FAILURE_REASON"
# Per-WAV subprocess timeout for kardome_runner (seconds). Unset or <=0 = no timeout.
ENV_BMT_KARDOME_CASE_TIMEOUT_SEC = "BMT_KARDOME_CASE_TIMEOUT_SEC"

# Pulumi config keys (bmt.tfvars.json) that map to repo vars
PULUMI_KEY_GCS_BUCKET = "gcs_bucket"
PULUMI_KEY_GCP_PROJECT = "gcp_project"
PULUMI_KEY_GCP_ZONE = "gcp_zone"
PULUMI_KEY_SERVICE_ACCOUNT = "service_account"
PULUMI_KEY_CLOUD_RUN_REGION = "cloud_run_region"
PULUMI_KEY_CLOUD_RUN_JOB_CONTROL = "cloud_run_job_control"
PULUMI_KEY_CLOUD_RUN_JOB_STANDARD = "cloud_run_job_standard"
PULUMI_KEY_CLOUD_RUN_JOB_HEAVY = "cloud_run_job_heavy"
PULUMI_KEY_GCP_WIF_PROVIDER = "gcp_wif_provider"

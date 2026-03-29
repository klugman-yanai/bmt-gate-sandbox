"""Shared constants for BMT runtime and tools.

Single source of truth for STATUS_CONTEXT, env var names, Cloud Run defaults,
result path segments, and image build defaults. CI has a mirrored copy in
ci/src/bmtgate/contract/constants.py — the drift-guard test keeps them aligned.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Network / API
# ---------------------------------------------------------------------------
HTTP_TIMEOUT = 30
GITHUB_API_VERSION = "2022-11-28"
EXECUTABLE_MODE = 0o111

# GitHub status context (must match branch protection rule).
STATUS_CONTEXT = "BMT Gate"

# GCP zone: used at runtime (not overridable via env).
DEFAULT_GCP_ZONE = "europe-west4-a"

# VM path (Terraform bmt_repo_root default must match).
DEFAULT_REPO_ROOT = "/opt/bmt"

# Image build / policy defaults.
DEFAULT_IMAGE_FAMILY = "bmt-runtime"
DEFAULT_BASE_IMAGE_FAMILY = "ubuntu-2204-lts"
DEFAULT_BASE_IMAGE_PROJECT = "ubuntu-os-cloud"

# Cloud Run Workflow resource name.
DEFAULT_WORKFLOW_NAME = "bmt-workflow"

# Default Cloud Run region — override via CLOUD_RUN_REGION env var.
DEFAULT_CLOUD_RUN_REGION = "europe-west4"

# GitHub App JWT timing.
JWT_CLOCK_SKEW_SEC = 60
JWT_LIFETIME_SEC = 600

# ---------------------------------------------------------------------------
# Result path constants
# ---------------------------------------------------------------------------
CURRENT_JSON = "current.json"
LATEST_JSON = "latest.json"
CI_VERDICT_JSON = "ci_verdict.json"
MANAGER_SUMMARY_JSON = "manager_summary.json"

SNAPSHOTS_PREFIX = "snapshots"
LOGS_PREFIX = "logs"

POINTER_KEY_LATEST = "latest"
POINTER_KEY_LAST_PASSING = "last_passing"

LOG_DUMPS_PREFIX = "log-dumps"

# ---------------------------------------------------------------------------
# Cloud Run / FUSE
# ---------------------------------------------------------------------------
FUSE_MOUNT_ROOT = "/mnt/runtime"
TRIGGER_SUMMARIES_PREFIX = "triggers/summaries"

CLOUD_RUN_TASK_INDEX_ENV = "CLOUD_RUN_TASK_INDEX"
CLOUD_RUN_TASK_COUNT_ENV = "CLOUD_RUN_TASK_COUNT"
BMT_WORKFLOW_RUN_ID_ENV = "BMT_WORKFLOW_RUN_ID"

# ---------------------------------------------------------------------------
# Environment / repo variable names (single source of truth)
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
ENV_BMT_FINALIZE_REPOSITORY = "BMT_FINALIZE_REPOSITORY"
ENV_BMT_FINALIZE_HEAD_SHA = "BMT_FINALIZE_HEAD_SHA"
ENV_BMT_FINALIZE_PR_NUMBER = "BMT_FINALIZE_PR_NUMBER"
ENV_BMT_HANDOFF_RUN_URL = "BMT_HANDOFF_RUN_URL"
ENV_BMT_GCS_BUCKET_NAME = "BMT_GCS_BUCKET_NAME"
ENV_BMT_KARDOME_CASE_TIMEOUT_SEC = "BMT_KARDOME_CASE_TIMEOUT_SEC"

# Pulumi config keys.
PULUMI_KEY_GCS_BUCKET = "gcs_bucket"
PULUMI_KEY_GCP_PROJECT = "gcp_project"
PULUMI_KEY_GCP_ZONE = "gcp_zone"
PULUMI_KEY_SERVICE_ACCOUNT = "service_account"
PULUMI_KEY_CLOUD_RUN_REGION = "cloud_run_region"
PULUMI_KEY_CLOUD_RUN_JOB_CONTROL = "cloud_run_job_control"
PULUMI_KEY_CLOUD_RUN_JOB_STANDARD = "cloud_run_job_standard"
PULUMI_KEY_CLOUD_RUN_JOB_HEAVY = "cloud_run_job_heavy"
PULUMI_KEY_GCP_WIF_PROVIDER = "gcp_wif_provider"

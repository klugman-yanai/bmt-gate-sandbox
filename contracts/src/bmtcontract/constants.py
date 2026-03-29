"""Single source of truth for shared BMT constants."""

from __future__ import annotations

from bmtcontract.decisions import GateDecision, ReasonCode

# ---------------------------------------------------------------------------
# Network / API
# ---------------------------------------------------------------------------
HTTP_TIMEOUT = 30
# GitHub REST API version header value. This is a GitHub-published API release date,
# not "today's" date.
GITHUB_API_VERSION = "2026-03-10"
EXECUTABLE_MODE = 0o111

# GitHub status context used by the coordinator.
STATUS_CONTEXT = "BMT Gate"

# GCP zone: used at runtime (not overridable via env).
DEFAULT_GCP_ZONE = "europe-west4-a"

# VM path (Terraform bmt_repo_root default must match).
DEFAULT_REPO_ROOT = "/opt/bmt"

# Image build / policy defaults.
DEFAULT_IMAGE_FAMILY = "bmt-runtime"
DEFAULT_BASE_IMAGE_FAMILY = "ubuntu-2204-lts"
DEFAULT_BASE_IMAGE_PROJECT = "ubuntu-os-cloud"

# Cloud Run Workflow resource name — baked into infra (Pulumi); not a developer-configurable value.
DEFAULT_WORKFLOW_NAME = "bmt-workflow"

# Default Cloud Run region — override via CLOUD_RUN_REGION env var.
DEFAULT_CLOUD_RUN_REGION = "europe-west4"

# GitHub App JWT timing
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
POINTER_V2_KEY_LATEST_RUN_ID = "latest_run_id"
POINTER_V2_KEY_LAST_PASSING_RUN_ID = "last_passing_run_id"
POINTER_V2_KEY_PROMOTED_BY_WORKFLOW_RUN_ID = "promoted_by_workflow_run_id"

LOG_DUMPS_PREFIX = "log-dumps"

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------
RESULTS_POINTER_SCHEMA_VERSION = 2
REPORTING_METADATA_SCHEMA_VERSION = 2
FINALIZATION_RECORD_SCHEMA_VERSION = 2
LEASE_RECORD_SCHEMA_VERSION = 2
DISPATCH_RECEIPT_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Workflow outputs
# ---------------------------------------------------------------------------
WORKFLOW_OUTPUT_BMT_GATE_PASSED = "bmt_gate_passed"
WORKFLOW_OUTPUT_BMT_DISPATCH_CONFIRMED = "bmt_dispatch_confirmed"
WORKFLOW_OUTPUT_BMT_FINAL_STATE = "bmt_final_state"
WORKFLOW_OUTPUT_BMT_RECOVERY_USED = "bmt_recovery_used"
# Deprecated alias retained for compatibility while consumers migrate.
WORKFLOW_OUTPUT_BMT_DISPATCH_FALLBACK_USED = "bmt_dispatch_fallback_used"

# ---------------------------------------------------------------------------
# Cloud Run / FUSE constants
# ---------------------------------------------------------------------------
FUSE_MOUNT_ROOT = "/mnt/runtime"
TRIGGER_SUMMARIES_PREFIX = "triggers/summaries"

CLOUD_RUN_TASK_INDEX_ENV = "CLOUD_RUN_TASK_INDEX"
CLOUD_RUN_TASK_COUNT_ENV = "CLOUD_RUN_TASK_COUNT"

BMT_WORKFLOW_RUN_ID_ENV = "BMT_WORKFLOW_RUN_ID"

# ---------------------------------------------------------------------------
# Environment / repo variable names
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
ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK = "BMT_DISPATCH_REQUIRE_CANCEL_OK"
# Deprecated inverse compatibility flag; prefer ENV_BMT_DISPATCH_REQUIRE_CANCEL_OK.
ENV_BMT_ALLOW_UNSAFE_SUPERSEDE = "BMT_ALLOW_UNSAFE_SUPERSEDE"

# Pulumi config keys
PULUMI_KEY_GCS_BUCKET = "gcs_bucket"
PULUMI_KEY_GCP_PROJECT = "gcp_project"
PULUMI_KEY_GCP_ZONE = "gcp_zone"
PULUMI_KEY_SERVICE_ACCOUNT = "service_account"
PULUMI_KEY_CLOUD_RUN_REGION = "cloud_run_region"
PULUMI_KEY_CLOUD_RUN_JOB_CONTROL = "cloud_run_job_control"
PULUMI_KEY_CLOUD_RUN_JOB_STANDARD = "cloud_run_job_standard"
PULUMI_KEY_CLOUD_RUN_JOB_HEAVY = "cloud_run_job_heavy"
PULUMI_KEY_GCP_WIF_PROVIDER = "gcp_wif_provider"

# ---------------------------------------------------------------------------
# Decision string aliases
# ---------------------------------------------------------------------------
DECISION_ACCEPTED: str = GateDecision.ACCEPTED.value
DECISION_ACCEPTED_WITH_WARNINGS: str = GateDecision.ACCEPTED_WITH_WARNINGS.value
DECISION_REJECTED: str = GateDecision.REJECTED.value
DECISION_TIMEOUT: str = GateDecision.TIMEOUT.value

REASON_JOBS_SCHEMA_INVALID: str = ReasonCode.JOBS_SCHEMA_INVALID.value
REASON_BMT_NOT_DEFINED: str = ReasonCode.BMT_NOT_DEFINED.value
REASON_BMT_DISABLED: str = ReasonCode.BMT_DISABLED.value
REASON_SUPERSEDED: str = ReasonCode.SUPERSEDED.value
REASON_INCOMPLETE_PLAN: str = ReasonCode.INCOMPLETE_PLAN.value
REASON_RUNNER_FAILURES: str = ReasonCode.RUNNER_FAILURES.value
REASON_RUNNER_TIMEOUT: str = ReasonCode.RUNNER_TIMEOUT.value
REASON_DEMO_FORCE_PASS: str = ReasonCode.DEMO_FORCE_PASS.value
REASON_PARTIAL_MISSING: str = ReasonCode.PARTIAL_MISSING.value

__all__ = [name for name in globals() if name.isupper() or name in {"GateDecision", "ReasonCode"}]

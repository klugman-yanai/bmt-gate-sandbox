"""Shared constants for BMT GCP code.

This module is the single source of truth for PUBSUB_TOPIC_NAME, STATUS_CONTEXT, DEFAULT_REPO_ROOT,
and image build defaults (DEFAULT_IMAGE_FAMILY, DEFAULT_BASE_IMAGE_FAMILY, DEFAULT_BASE_IMAGE_PROJECT).
- Code and CI read these directly. Terraform cannot import Python, so it keeps matching literals in
  main.tf / variables.tf; tests/infra/test_terraform_bmt_config_parity.py fails if they diverge.
"""

from __future__ import annotations

HTTP_TIMEOUT = 30
GITHUB_API_VERSION = "2022-11-28"
EXECUTABLE_MODE = 0o111

# Pub/Sub and GitHub status (single source of truth; Terraform topic name must match PUBSUB_TOPIC_NAME).
PUBSUB_TOPIC_NAME = "bmt-triggers"
STATUS_CONTEXT = "BMT Gate"

# VM path (Terraform bmt_repo_root default must match).
DEFAULT_REPO_ROOT = "/opt/bmt"

# GCP zone: used at runtime (not overridable via env). Terraform still requires gcp_zone in
# bmt.tfvars.json (no default there); this constant is the single value used by code/CI.
DEFAULT_GCP_ZONE = "europe-west4-a"

# Image build / policy defaults (single source; Terraform image_family default must match DEFAULT_IMAGE_FAMILY).
DEFAULT_IMAGE_FAMILY = "bmt-runtime"
DEFAULT_BASE_IMAGE_FAMILY = "ubuntu-2204-lts"
DEFAULT_BASE_IMAGE_PROJECT = "ubuntu-os-cloud"

# ---------------------------------------------------------------------------
# Result path constants (L0 leaf — no gcp.image imports allowed)
# ---------------------------------------------------------------------------
# Canonical JSON filenames under {results_prefix}/snapshots/{run_id}/
CURRENT_JSON = "current.json"
LATEST_JSON = "latest.json"
CI_VERDICT_JSON = "ci_verdict.json"
MANAGER_SUMMARY_JSON = "manager_summary.json"

# Directory segments under results_prefix
SNAPSHOTS_PREFIX = "snapshots"
LOGS_PREFIX = "logs"

# Pointer keys inside current.json
POINTER_KEY_LATEST = "latest"
POINTER_KEY_LAST_PASSING = "last_passing"

# ---------------------------------------------------------------------------
# Registry / runtime config path constants
# ---------------------------------------------------------------------------
RUNTIME_CONFIG_PREFIX = "config"
BMT_PROJECTS_FILENAME = "bmt_projects.json"

# ---------------------------------------------------------------------------
# Trigger family path segments (relative to bucket root)
# ---------------------------------------------------------------------------
TRIGGER_RUNS_PREFIX = "triggers/runs"
TRIGGER_ACKS_PREFIX = "triggers/acks"
TRIGGER_STATUS_PREFIX = "triggers/status"
WORKFLOW_UPLOADED_PREFIX = "_workflow/uploaded"
LOG_DUMPS_PREFIX = "log-dumps"
LOG_DUMP_REQUESTS_PREFIX = "log-dump-requests"

# ---------------------------------------------------------------------------
# Trigger decision constants (aligned with existing lowercase codes)
# ---------------------------------------------------------------------------
DECISION_ACCEPTED = "accepted"
DECISION_REJECTED = "rejected"

# Reason codes for rejected legs
REASON_JOBS_SCHEMA_INVALID = "jobs_schema_invalid"
REASON_BMT_NOT_DEFINED = "bmt_not_defined"
REASON_BMT_DISABLED = "bmt_disabled"
REASON_SUPERSEDED = "superseded"
REASON_RUNNER_FAILURES = "runner_failures"
REASON_RUNNER_TIMEOUT = "runner_timeout"
REASON_DEMO_FORCE_PASS = "demo_force_pass"

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
REASON_PARTIAL_MISSING = "partial_missing"

# Cloud Run task index env var (set automatically by Cloud Run)
CLOUD_RUN_TASK_INDEX_ENV = "CLOUD_RUN_TASK_INDEX"
CLOUD_RUN_TASK_COUNT_ENV = "CLOUD_RUN_TASK_COUNT"

# Env vars set by the Workflow when invoking the Cloud Run Job
BMT_TRIGGER_OBJECT_ENV = "BMT_TRIGGER_OBJECT"
BMT_WORKFLOW_RUN_ID_ENV = "BMT_WORKFLOW_RUN_ID"

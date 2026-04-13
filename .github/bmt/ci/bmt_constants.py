"""Thin facade re-exporting gcp.image.config symbols needed by the CI layer.

Import from here rather than directly from gcp.image.config so that CI callers
have a single stable boundary. When gcp/image/config/ is refactored, only this
file needs updating.
"""

from __future__ import annotations

from gcp.image.config.constants import (
    DECISION_ACCEPTED as DECISION_ACCEPTED,
    DECISION_ACCEPTED_WITH_WARNINGS as DECISION_ACCEPTED_WITH_WARNINGS,
    DECISION_REJECTED as DECISION_REJECTED,
    DECISION_TIMEOUT as DECISION_TIMEOUT,
    DEFAULT_CLOUD_RUN_REGION as DEFAULT_CLOUD_RUN_REGION,
    DEFAULT_WORKFLOW_NAME as DEFAULT_WORKFLOW_NAME,
    ENV_BMT_CONTROL_JOB as ENV_BMT_CONTROL_JOB,
    ENV_BMT_STATUS_CONTEXT as ENV_BMT_STATUS_CONTEXT,
    ENV_BMT_TASK_HEAVY_JOB as ENV_BMT_TASK_HEAVY_JOB,
    ENV_BMT_TASK_STANDARD_JOB as ENV_BMT_TASK_STANDARD_JOB,
    ENV_CLOUD_RUN_REGION as ENV_CLOUD_RUN_REGION,
    ENV_GCP_PROJECT as ENV_GCP_PROJECT,
    ENV_GCP_SA_EMAIL as ENV_GCP_SA_EMAIL,
    ENV_GCP_WIF_PROVIDER as ENV_GCP_WIF_PROVIDER,
    ENV_GCS_BUCKET as ENV_GCS_BUCKET,
    STATUS_CONTEXT as STATUS_CONTEXT,
)
from gcp.image.config.decisions import GateDecision as GateDecision
from gcp.image.config.env_parse import is_truthy_env_value as is_truthy_env_value
from gcp.image.config.value_types import sanitize_run_id as sanitize_run_id

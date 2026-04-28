"""Build GCP Console URLs for operators (Cloud Run job execution logs, etc.)."""

from __future__ import annotations

import os
from urllib.parse import quote

from runtime.config.constants import DEFAULT_CLOUD_RUN_REGION, ENV_CLOUD_RUN_REGION, ENV_GCP_PROJECT


def cloud_run_job_execution_logs_console_url() -> str | None:
    """Link to this container's Cloud Run **job execution** Logs tab (stdout/stderr in Cloud Logging).

    Uses the `Cloud Run jobs`_ runtime contract: ``CLOUD_RUN_JOB``, ``CLOUD_RUN_EXECUTION``,
    plus project and region.

    .. _Cloud Run jobs: https://cloud.google.com/run/docs/container-contract
    """
    job = (os.environ.get("CLOUD_RUN_JOB") or "").strip()
    execution = (os.environ.get("CLOUD_RUN_EXECUTION") or "").strip()
    region = (os.environ.get(ENV_CLOUD_RUN_REGION) or "").strip() or DEFAULT_CLOUD_RUN_REGION
    project = (os.environ.get(ENV_GCP_PROJECT) or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not job or not execution or not project:
        return None
    # Path segments must be URL-encoded for unusual job/execution names.
    enc_job = quote(job, safe="")
    enc_exe = quote(execution, safe="")
    return (
        f"https://console.cloud.google.com/run/jobs/details/{region}/{enc_job}/"
        f"executions/{enc_exe}/logs?project={quote(project, safe='')}"
    )

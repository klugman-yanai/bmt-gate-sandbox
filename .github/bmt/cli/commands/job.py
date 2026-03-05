"""Cloud Run Job execution command."""

from __future__ import annotations

import os
import subprocess
import time

from cli.shared import require_env


def run_execute_cloud_run_job() -> None:
    """Execute a Cloud Run Job for this workflow run (cloud_run_job backend).

    Reads: BMT_CLOUD_RUN_JOB, BMT_CLOUD_RUN_REGION, GCP_PROJECT, GITHUB_RUN_ID.
    The job container reads WORKFLOW_RUN_ID to enter single-trigger mode.
    Uses --async so the step returns immediately; the job is tracked via GCS ack.
    """
    job_name = require_env("BMT_CLOUD_RUN_JOB")
    region = require_env("BMT_CLOUD_RUN_REGION")
    project = require_env("GCP_PROJECT")
    workflow_run_id = os.environ.get("GITHUB_RUN_ID", "local")

    cmd = [
        "gcloud",
        "run",
        "jobs",
        "execute",
        job_name,
        f"--region={region}",
        f"--project={project}",
        "--async",
        f"--update-env-vars=WORKFLOW_RUN_ID={workflow_run_id}",
        "--format=json",
    ]

    max_attempts = 3
    last_stderr = ""
    for attempt in range(1, max_attempts + 1):
        print(f"Executing Cloud Run Job '{job_name}' (attempt {attempt}/{max_attempts})…")
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Cloud Run Job execution submitted for workflow_run_id={workflow_run_id}")
            return
        last_stderr = result.stderr.strip()
        print(f"::warning::gcloud run jobs execute failed (attempt {attempt}): {last_stderr}")
        if attempt < max_attempts:
            time.sleep(5 * attempt)

    raise RuntimeError(
        f"Failed to submit Cloud Run Job '{job_name}' after {max_attempts} attempts. "
        f"Last error: {last_stderr}"
    )

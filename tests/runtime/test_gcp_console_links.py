from __future__ import annotations

import pytest

from runtime.config.constants import ENV_CLOUD_RUN_REGION, ENV_GCP_PROJECT
from runtime.gcp_console_links import cloud_run_job_execution_logs_console_url


def test_cloud_run_job_execution_logs_console_url_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUD_RUN_JOB", "bmt-task-standard")
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "bmt-task-standard-abcd")
    monkeypatch.setenv(ENV_GCP_PROJECT, "my-proj")
    monkeypatch.setenv(ENV_CLOUD_RUN_REGION, "europe-west4")
    url = cloud_run_job_execution_logs_console_url()
    assert url is not None
    assert "console.cloud.google.com/run/jobs/details/europe-west4/bmt-task-standard/executions/" in url
    assert "project=my-proj" in url


def test_cloud_run_job_execution_logs_console_url_none_when_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    assert cloud_run_job_execution_logs_console_url() is None

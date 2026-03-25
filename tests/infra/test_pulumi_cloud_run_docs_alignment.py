"""Regression tests for Cloud Run docs-alignment in Pulumi infra."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.unit


def _load_module(module_name: str, relative_path: str):
    module_path = _REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader, f"Failed to load module spec for {module_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_workflow_connector_timeout_default_covers_job_timeout() -> None:
    config_mod = _load_module("pulumi_infra_config_cloud_run", "infra/pulumi/pulumi_stack_config.py")
    cfg = config_mod.InfraConfig(
        gcp_project="demo-project",
        gcp_zone="europe-west4-a",
        gcs_bucket="demo-bucket",
        service_account="demo@example.com",
    )

    assert cfg.cloud_run_workflow_connector_timeout_sec >= cfg.cloud_run_task_timeout_sec


@pytest.mark.parametrize("field_name", ["cloud_run_job_sa_name", "cloud_run_workflow_sa_name"])
def test_cloud_run_service_account_names_must_be_non_empty(field_name: str) -> None:
    config_mod = _load_module("pulumi_infra_config_sa_names", "infra/pulumi/pulumi_stack_config.py")
    kwargs = {
        "gcp_project": "demo-project",
        "gcp_zone": "europe-west4-a",
        "gcs_bucket": "demo-bucket",
        "service_account": "demo@example.com",
        field_name: " ",
    }

    with pytest.raises(ValueError, match=field_name):
        config_mod.InfraConfig(**kwargs)


def test_workflow_connector_timeout_rejects_shorter_than_job_timeout() -> None:
    config_mod = _load_module("pulumi_infra_config_validation", "infra/pulumi/pulumi_stack_config.py")

    with pytest.raises(ValueError, match="cloud_run_workflow_connector_timeout_sec"):
        config_mod.InfraConfig(
            gcp_project="demo-project",
            gcp_zone="europe-west4-a",
            gcs_bucket="demo-bucket",
            service_account="demo@example.com",
            cloud_run_task_timeout_sec=3600,
            cloud_run_workflow_connector_timeout_sec=3599,
        )


def test_rendered_workflow_source_includes_connector_timeouts_for_direct_workflow_jobs() -> None:
    workflow_mod = _load_module("pulumi_infra_workflow_template", "infra/pulumi/workflow_template.py")
    template_path = _REPO_ROOT / "infra" / "pulumi" / "workflow.yaml"

    rendered = workflow_mod.render_workflow_source(template_path=template_path, connector_timeout_sec=3900)

    assert "__CONNECTOR_TIMEOUT_SEC__" not in rendered
    assert rendered.count("connector_params:") == 5
    assert rendered.count("timeout: 3900") == 5
    assert 'value: "plan"' in rendered
    assert 'value: "standard"' in rendered
    assert 'value: "heavy"' in rendered
    assert 'value: "coordinator"' in rendered
    assert 'value: "finalize-failure"' in rendered
    assert "bmt_pipeline:" in rendered
    assert "run_finalize_failure_job:" in rendered


def test_enabled_github_app_secret_names_cover_primary_and_dev_profiles() -> None:
    workflow_mod = _load_module("pulumi_infra_secret_scope", "infra/pulumi/workflow_template.py")

    secret_names = workflow_mod.github_app_secret_names()

    assert secret_names == [
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_APP_DEV_ID",
        "GITHUB_APP_DEV_INSTALLATION_ID",
        "GITHUB_APP_DEV_PRIVATE_KEY",
    ]


def test_pulumi_stack_keeps_job_overrides_role_and_secret_level_access() -> None:
    main_py = (_REPO_ROOT / "infra" / "pulumi" / "__main__.py").read_text(encoding="utf-8")

    assert 'role="roles/run.jobsExecutorWithOverrides"' in main_py
    assert '"github-wif-invokes-control-job"' in main_py
    assert 'role="roles/workflows.invoker"' in main_py
    assert '"github-wif-workflows-invoker"' in main_py
    assert 'role="roles/run.invoker"' not in main_py
    assert "gcp.eventarc.Trigger(" not in main_py
    assert "gcp.compute.Instance(" not in main_py
    assert "gcp.pubsub.Topic(" not in main_py
    assert "gcp.secretmanager.SecretIamMember(" in main_py

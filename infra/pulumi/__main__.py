"""Unified Cloud Run BMT infrastructure."""

from __future__ import annotations

import posixpath
import tempfile
from pathlib import Path

import pulumi
import pulumi_gcp as gcp
from pulumi_stack_config import load_config
from workflow_template import github_app_secret_names, render_workflow_source

cfg = load_config()

artifact_registry = gcp.artifactregistry.Repository(
    "bmt-images",
    repository_id=cfg.artifact_registry_repo,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    format="DOCKER",
    description="BMT Cloud Run container images",
)

job_runner_sa = gcp.serviceaccount.Account(
    "bmt-job-runner-sa",
    account_id=cfg.cloud_run_job_sa_name,
    display_name="BMT Cloud Run Job Runner",
    project=cfg.gcp_project,
)

workflow_sa = gcp.serviceaccount.Account(
    "bmt-workflow-sa",
    account_id=cfg.cloud_run_workflow_sa_name,
    display_name="BMT Trigger Workflow",
    project=cfg.gcp_project,
)

github_wif_member = f"serviceAccount:{cfg.service_account}"


def _secret_env(name: str) -> gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs:
    return gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
        name=name,
        value_source=gcp.cloudrunv2.JobTemplateTemplateContainerEnvValueSourceArgs(
            secret_key_ref=gcp.cloudrunv2.JobTemplateTemplateContainerEnvValueSourceSecretKeyRefArgs(
                secret=name,
                version="latest",
            )
        ),
    )


def _job(
    resource_name: str,
    *,
    job_name: str,
    cpu: str,
    memory: str,
) -> gcp.cloudrunv2.Job:
    return gcp.cloudrunv2.Job(
        resource_name,
        name=job_name,
        location=cfg.cloud_run_region,
        project=cfg.gcp_project,
        launch_stage="GA",
        template=gcp.cloudrunv2.JobTemplateArgs(
            task_count=1,
            template=gcp.cloudrunv2.JobTemplateTemplateArgs(
                service_account=job_runner_sa.email,
                timeout=f"{cfg.cloud_run_task_timeout_sec}s",
                max_retries=1,
                containers=[
                    gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                        image=f"{cfg.cloud_run_image_uri}:latest",
                        envs=[
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(name="GCS_BUCKET", value=cfg.gcs_bucket),
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                name="GCP_PROJECT", value=cfg.gcp_project
                            ),
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                name="BMT_RUNTIME_ROOT", value="/mnt/runtime"
                            ),
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                name="BMT_FRAMEWORK_WORKSPACE",
                                value=posixpath.join(tempfile.gettempdir(), "bmt-framework"),
                            ),
                            _secret_env("GITHUB_APP_ID"),
                            _secret_env("GITHUB_APP_INSTALLATION_ID"),
                            _secret_env("GITHUB_APP_PRIVATE_KEY"),
                            _secret_env("GITHUB_APP_DEV_ID"),
                            _secret_env("GITHUB_APP_DEV_INSTALLATION_ID"),
                            _secret_env("GITHUB_APP_DEV_PRIVATE_KEY"),
                        ],
                        resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                            limits={"cpu": cpu, "memory": memory}
                        ),
                        volume_mounts=[
                            gcp.cloudrunv2.JobTemplateTemplateContainerVolumeMountArgs(
                                name="runtime-data",
                                mount_path="/mnt/runtime",
                            )
                        ],
                    )
                ],
                volumes=[
                    gcp.cloudrunv2.JobTemplateTemplateVolumeArgs(
                        name="runtime-data",
                        gcs=gcp.cloudrunv2.JobTemplateTemplateVolumeGcsArgs(
                            bucket=cfg.gcs_bucket,
                            read_only=False,
                        ),
                    )
                ],
            ),
        ),
    )


cloud_run_job_control = _job(
    "bmt-control",
    job_name="bmt-control",
    cpu=cfg.cloud_run_cpu_standard,
    memory=cfg.cloud_run_memory_standard,
)

cloud_run_job_standard = _job(
    "bmt-task-standard",
    job_name="bmt-task-standard",
    cpu=cfg.cloud_run_cpu_standard,
    memory=cfg.cloud_run_memory_standard,
)

cloud_run_job_heavy = _job(
    "bmt-task-heavy",
    job_name="bmt-task-heavy",
    cpu=cfg.cloud_run_cpu_heavy,
    memory=cfg.cloud_run_memory_heavy,
)

workflow_source = render_workflow_source(
    template_path=Path(__file__).parent / "workflow.yaml",
    connector_timeout_sec=cfg.cloud_run_workflow_connector_timeout_sec,
)
github_app_secret_ids = github_app_secret_names()

bmt_workflow = gcp.workflows.Workflow(
    "bmt-workflow",
    name="bmt-workflow",
    region=cfg.cloud_run_region,
    project=cfg.gcp_project,
    description="Direct GitHub -> Workflow -> Cloud Run BMT pipeline",
    service_account=workflow_sa.id,
    source_contents=workflow_source,
)

# pulumi-gcp 9.x does not expose gcp.workflows.WorkflowIamMember (no workflow-scoped IAM
# in the provider schema). Grant at project scope so GitHub Actions (impersonating
# bmt-runner-sa via WIF) can start/cancel executions (see workflows_api.py).
gcp.projects.IAMMember(
    "github-wif-workflows-invoker",
    project=cfg.gcp_project,
    role="roles/workflows.invoker",
    member=github_wif_member,
)

gcp.storage.BucketIAMMember(
    "job-runner-bucket-writer",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectAdmin",
    member=pulumi.Output.concat("serviceAccount:", job_runner_sa.email),
)

for secret_name in github_app_secret_ids:
    gcp.secretmanager.SecretIamMember(
        f"job-runner-secret-{secret_name.lower().replace('_', '-')}",
        project=cfg.gcp_project,
        secret_id=secret_name,
        role="roles/secretmanager.secretAccessor",
        member=pulumi.Output.concat("serviceAccount:", job_runner_sa.email),
    )

for member_name, job in {
    "workflow-invokes-control-job": cloud_run_job_control,
    "workflow-invokes-standard-job": cloud_run_job_standard,
    "workflow-invokes-heavy-job": cloud_run_job_heavy,
}.items():
    gcp.cloudrunv2.JobIamMember(
        member_name,
        name=job.name,
        location=cfg.cloud_run_region,
        project=cfg.gcp_project,
        role="roles/run.jobsExecutorWithOverrides",
        member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
    )

gcp.cloudrunv2.JobIamMember(
    "github-wif-invokes-control-job",
    name=cloud_run_job_control.name,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    role="roles/run.jobsExecutorWithOverrides",
    member=github_wif_member,
)

gcp.storage.BucketIAMMember(
    "workflow-sa-bucket-reader",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectViewer",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

gcp.projects.IAMMember(
    "workflow-sa-log-writer",
    project=cfg.gcp_project,
    role="roles/logging.logWriter",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

pulumi.export("gcs_bucket", cfg.gcs_bucket)
pulumi.export("gcp_project", cfg.gcp_project)
pulumi.export("gcp_zone", cfg.gcp_zone)
pulumi.export("cloud_run_region", cfg.cloud_run_region)
pulumi.export("service_account", cfg.service_account)
pulumi.export("gcp_wif_provider", cfg.gcp_wif_provider or "")
pulumi.export("artifact_registry_repo", artifact_registry.name)
pulumi.export("cloud_run_job_control", cloud_run_job_control.name)
pulumi.export("cloud_run_job_standard", cloud_run_job_standard.name)
pulumi.export("cloud_run_job_heavy", cloud_run_job_heavy.name)
pulumi.export("cloud_run_image_uri", cfg.cloud_run_image_uri)
pulumi.export("workflow_name", bmt_workflow.name)
pulumi.export("job_runner_sa", job_runner_sa.email)
pulumi.export("workflow_sa", workflow_sa.email)

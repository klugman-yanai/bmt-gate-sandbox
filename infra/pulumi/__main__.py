"""BMT Gate infrastructure: VM, Pub/Sub, IAM.

Replaces infra/terraform/main.tf. Resources are identical; config comes from bmt.tfvars.json.
"""

from __future__ import annotations

from pathlib import Path

import pulumi
import pulumi_gcp as gcp
from config import load_config

cfg = load_config()

# Resolve startup script (path is relative to infra/pulumi/)
startup_script_path = (Path(__file__).parent / cfg.startup_wrapper_script_path).resolve()
if not startup_script_path.is_file():
    raise FileNotFoundError(f"Startup script not found: {startup_script_path}")
startup_script = startup_script_path.read_text(encoding="utf-8")

# --- Data sources ---

project_info = gcp.organizations.get_project(project_id=cfg.gcp_project)

resolved_image: str | pulumi.Output[str]
if cfg.image_name:
    resolved_image = cfg.image_name
else:
    image = gcp.compute.get_image(family=cfg.image_family, project=cfg.gcp_project)
    resolved_image = image.self_link

# --- VM ---

bmt_vm = gcp.compute.Instance(
    "bmt-vm",
    name=cfg.bmt_vm_name,
    machine_type=cfg.machine_type,
    zone=cfg.gcp_zone,
    project=cfg.gcp_project,
    tags=list(cfg.tags) if cfg.tags else None,
    boot_disk=gcp.compute.InstanceBootDiskArgs(
        initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(
            image=resolved_image,
            size=cfg.disk_size_gb,
            type=cfg.disk_type,
        ),
    ),
    network_interfaces=[
        gcp.compute.InstanceNetworkInterfaceArgs(
            network=cfg.network,
            subnetwork=cfg.subnetwork or None,
        ),
    ],
    service_account=gcp.compute.InstanceServiceAccountArgs(
        email=cfg.service_account,
        scopes=list(cfg.scopes),
    ),
    metadata={
        "GCS_BUCKET": cfg.gcs_bucket,
        "BMT_REPO_ROOT": cfg.bmt_repo_root,
        "GCP_PROJECT": cfg.gcp_project,
        "BMT_PUBSUB_SUBSCRIPTION": f"bmt-vm-{cfg.bmt_vm_name}",
        "startup-script": startup_script,
        "startup-script-url": "",
        "bmt_image_family": cfg.image_family,
        "bmt_image_version": resolved_image,
        "bmt_managed_by": "pulumi",
    },
    labels={
        "bmt-managed-by": "pulumi",
        "bmt-image-family": cfg.image_family.lower().replace("_", "-"),
    },
    desired_status="TERMINATED",
    opts=pulumi.ResourceOptions(
        ignore_changes=["metadata.startup-script"],
    ),
)

# --- Pub/Sub ---

triggers_topic = gcp.pubsub.Topic(
    "bmt-triggers",
    name="bmt-triggers",
    project=cfg.gcp_project,
)

triggers_dlq_topic = gcp.pubsub.Topic(
    "bmt-triggers-dlq",
    name="bmt-triggers-dlq",
    project=cfg.gcp_project,
)

bmt_subscription = gcp.pubsub.Subscription(
    "bmt-vm-subscription",
    name=f"bmt-vm-{cfg.bmt_vm_name}",
    topic=triggers_topic.id,
    project=cfg.gcp_project,
    ack_deadline_seconds=600,
    message_retention_duration="3600s",
    dead_letter_policy=gcp.pubsub.SubscriptionDeadLetterPolicyArgs(
        dead_letter_topic=triggers_dlq_topic.id,
        max_delivery_attempts=5,
    ),
)

# --- IAM ---

# VM SA can consume from its subscription
gcp.pubsub.SubscriptionIAMMember(
    "vm-subscriber",
    project=cfg.gcp_project,
    subscription=bmt_subscription.name,
    role="roles/pubsub.subscriber",
    member=f"serviceAccount:{cfg.service_account}",
)

# CI SA can publish to the trigger topic
gcp.pubsub.TopicIAMMember(
    "ci-publisher",
    project=cfg.gcp_project,
    topic=triggers_topic.name,
    role="roles/pubsub.publisher",
    member=f"serviceAccount:{cfg.service_account}",
)

# Pub/Sub system SA can forward dead letters to DLQ
gcp.pubsub.TopicIAMMember(
    "dlq-publisher",
    project=cfg.gcp_project,
    topic=triggers_dlq_topic.name,
    role="roles/pubsub.publisher",
    member=f"serviceAccount:service-{project_info.number}@gcp-sa-pubsub.iam.gserviceaccount.com",
)

# ===================================================================
# Cloud Run Infrastructure
# ===================================================================

# --- Artifact Registry ---

artifact_registry = gcp.artifactregistry.Repository(
    "bmt-images",
    repository_id=cfg.artifact_registry_repo,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    format="DOCKER",
    description="BMT orchestrator container images",
)

# --- Service Accounts ---

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

# --- Cloud Run Jobs ---

cloud_run_job_standard = gcp.cloudrunv2.Job(
    "bmt-orchestrator-standard",
    name="bmt-orchestrator-standard",
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    launch_stage="GA",
    template=gcp.cloudrunv2.JobTemplateArgs(
        task_count=1,  # overridden per-execution by Workflow
        template=gcp.cloudrunv2.JobTemplateTemplateArgs(
            service_account=job_runner_sa.email,
            timeout=f"{cfg.cloud_run_task_timeout_sec}s",
            max_retries=1,
            containers=[
                gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                    image=f"{cfg.cloud_run_image_uri}:latest",
                    resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                        limits={
                            "cpu": cfg.cloud_run_cpu_standard,
                            "memory": cfg.cloud_run_memory_standard,
                        },
                    ),
                ),
            ],
            volumes=[
                gcp.cloudrunv2.JobTemplateTemplateVolumeArgs(
                    name="runtime-data",
                    gcs=gcp.cloudrunv2.JobTemplateTemplateVolumeGcsArgs(
                        bucket=cfg.gcs_bucket,
                        read_only=False,
                    ),
                ),
            ],
        ),
    ),
)

cloud_run_job_heavy = gcp.cloudrunv2.Job(
    "bmt-orchestrator-heavy",
    name="bmt-orchestrator-heavy",
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
                    resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                        limits={
                            "cpu": cfg.cloud_run_cpu_heavy,
                            "memory": cfg.cloud_run_memory_heavy,
                        },
                    ),
                ),
            ],
            volumes=[
                gcp.cloudrunv2.JobTemplateTemplateVolumeArgs(
                    name="runtime-data",
                    gcs=gcp.cloudrunv2.JobTemplateTemplateVolumeGcsArgs(
                        bucket=cfg.gcs_bucket,
                        read_only=False,
                    ),
                ),
            ],
        ),
    ),
)

# --- Workflows ---

workflow_source = (Path(__file__).parent / "workflow.yaml").read_text(encoding="utf-8")

bmt_workflow = gcp.workflows.Workflow(
    "bmt-trigger-workflow",
    name="bmt-trigger-workflow",
    region=cfg.cloud_run_region,
    project=cfg.gcp_project,
    description="Routes GCS trigger events to BMT Cloud Run Jobs",
    service_account=workflow_sa.id,
    source_contents=workflow_source,
)

# --- Eventarc ---

eventarc_trigger = gcp.eventarc.Trigger(
    "bmt-gcs-trigger",
    name="bmt-gcs-trigger",
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    matching_criterias=[
        gcp.eventarc.TriggerMatchingCriteriaArgs(
            attribute="type",
            value="google.cloud.storage.object.v1.finalized",
        ),
        gcp.eventarc.TriggerMatchingCriteriaArgs(
            attribute="bucket",
            value=cfg.gcs_bucket,
        ),
    ],
    destination=gcp.eventarc.TriggerDestinationArgs(
        workflow=bmt_workflow.id,
    ),
    service_account=workflow_sa.email,
)

# --- IAM: Job Runner SA ---

# Read access to bucket (config, triggers, datasets)
gcp.storage.BucketIAMMember(
    "job-runner-bucket-reader",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectViewer",
    member=pulumi.Output.concat("serviceAccount:", job_runner_sa.email),
)

# Write access to bucket (summaries, results, acks)
gcp.storage.BucketIAMMember(
    "job-runner-bucket-writer",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectCreator",
    member=pulumi.Output.concat("serviceAccount:", job_runner_sa.email),
)

# --- IAM: Workflow SA ---

# Invoke Cloud Run Jobs
gcp.cloudrunv2.JobIamMember(
    "workflow-invokes-standard-job",
    name=cloud_run_job_standard.name,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    role="roles/run.invoker",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

gcp.cloudrunv2.JobIamMember(
    "workflow-invokes-heavy-job",
    name=cloud_run_job_heavy.name,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    role="roles/run.invoker",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

# Read trigger files from bucket
gcp.storage.BucketIAMMember(
    "workflow-sa-bucket-reader",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectViewer",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

# Receive Eventarc events
gcp.projects.IAMMember(
    "workflow-sa-eventarc-receiver",
    project=cfg.gcp_project,
    role="roles/eventarc.eventReceiver",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

# Workflow logging
gcp.projects.IAMMember(
    "workflow-sa-log-writer",
    project=cfg.gcp_project,
    role="roles/logging.logWriter",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

# --- Exports (replaces outputs.tf) ---

pulumi.export("gcs_bucket", cfg.gcs_bucket)
pulumi.export("gcp_project", cfg.gcp_project)
pulumi.export("gcp_zone", cfg.gcp_zone)
pulumi.export("bmt_vm_name", cfg.bmt_vm_name)
pulumi.export("bmt_repo_root", cfg.bmt_repo_root)
pulumi.export("service_account", cfg.service_account)
pulumi.export("pubsub_subscription", bmt_subscription.name)
pulumi.export("pubsub_topic", triggers_topic.name)
pulumi.export("bmt_vm_pool", cfg.bmt_vm_pool)
pulumi.export("bmt_vm_base", cfg.bmt_vm_base)

# Cloud Run exports
pulumi.export("artifact_registry_repo", artifact_registry.name)
pulumi.export("cloud_run_job_standard", cloud_run_job_standard.name)
pulumi.export("cloud_run_job_heavy", cloud_run_job_heavy.name)
pulumi.export("cloud_run_image_uri", cfg.cloud_run_image_uri)
pulumi.export("workflow_name", bmt_workflow.name)
pulumi.export("eventarc_trigger", eventarc_trigger.name)
pulumi.export("job_runner_sa", job_runner_sa.email)
pulumi.export("workflow_sa", workflow_sa.email)

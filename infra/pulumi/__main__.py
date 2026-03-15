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

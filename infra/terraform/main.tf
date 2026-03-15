terraform {
  required_version = ">= 1.7.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0.0"
    }
  }

  backend "gcs" {
    # Configured via -backend-config at init time:
    #   terraform init -backend-config="bucket=<your-bucket>" -backend-config="prefix=terraform/bmt-vm"
  }
}

provider "google" {
  project = var.gcp_project
}

# ---------------------------------------------------------------------------
# Image resolution — use explicit name if provided, else resolve from family
# ---------------------------------------------------------------------------

data "google_compute_image" "bmt_runtime" {
  count   = var.image_name == "" ? 1 : 0
  family  = var.image_family
  project = var.gcp_project
}

locals {
  resolved_image = var.image_name != "" ? var.image_name : data.google_compute_image.bmt_runtime[0].self_link
  startup_script = file(var.startup_wrapper_script_path)
}

# ---------------------------------------------------------------------------
# BMT VM
# ---------------------------------------------------------------------------

resource "google_compute_instance" "bmt_vm" {
  name         = var.bmt_vm_name
  machine_type = var.machine_type
  zone         = var.gcp_zone

  tags = var.tags

  boot_disk {
    initialize_params {
      image = local.resolved_image
      size  = var.disk_size_gb
      type  = var.disk_type
    }
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnetwork != "" ? var.subnetwork : null
  }

  service_account {
    email  = var.service_account
    scopes = var.scopes
  }

  metadata = {
    GCS_BUCKET              = var.gcs_bucket
    BMT_REPO_ROOT           = var.bmt_repo_root
    GCP_PROJECT             = var.gcp_project
    BMT_PUBSUB_SUBSCRIPTION = "bmt-vm-${var.bmt_vm_name}"
    "startup-script"        = local.startup_script
    "startup-script-url"    = ""
    bmt_image_family        = var.image_family
    bmt_image_version       = local.resolved_image
    bmt_managed_by          = "terraform"
  }

  labels = {
    bmt-managed-by  = "terraform"
    bmt-image-family = replace(lower(var.image_family), "_", "-")
  }

  # Allow Terraform to start/stop the VM without destroying it.
  # lifecycle.prevent_destroy guards against accidental `terraform destroy`.
  lifecycle {
    prevent_destroy       = true
    ignore_changes        = [metadata["startup-script"]]  # updated by bmt sync-vm-metadata
  }

  # VM starts in TERMINATED state after creation; the workflow starts it per-run.
  desired_status = "TERMINATED"
}

# ---------------------------------------------------------------------------
# Pub/Sub trigger delivery
# ---------------------------------------------------------------------------
# Topic name: canonical value in gcp/image/config/constants.py PUBSUB_TOPIC_NAME.
# Keep this literal in sync; tests/infra/test_terraform_bmt_config_parity.py enforces.

resource "google_pubsub_topic" "bmt_triggers" {
  name    = "bmt-triggers"
  project = var.gcp_project
}

resource "google_pubsub_topic" "bmt_triggers_dlq" {
  name    = "bmt-triggers-dlq"
  project = var.gcp_project
}

resource "google_pubsub_subscription" "bmt_vm" {
  name    = "bmt-vm-${var.bmt_vm_name}"
  topic   = google_pubsub_topic.bmt_triggers.id
  project = var.gcp_project

  # Ack deadline: long enough to cover VM boot + leg startup (up to 10 min).
  ack_deadline_seconds = 600

  # Retain undelivered messages for 1 hour (matches BMT_STALE_TRIGGER_AGE_HOURS).
  message_retention_duration = "3600s"

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.bmt_triggers_dlq.id
    max_delivery_attempts = 5
  }
}

# VM service account → subscriber on its subscription
resource "google_pubsub_subscription_iam_member" "vm_subscriber" {
  project      = var.gcp_project
  subscription = google_pubsub_subscription.bmt_vm.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${var.service_account}"
}

# CI service account (same SA) → publisher on the topic
resource "google_pubsub_topic_iam_member" "ci_publisher" {
  project = var.gcp_project
  topic   = google_pubsub_topic.bmt_triggers.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.service_account}"
}

# DLQ topic needs pubsub SA to forward dead letters
resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  project = var.gcp_project
  topic   = google_pubsub_topic.bmt_triggers_dlq.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

data "google_project" "project" {
  project_id = var.gcp_project
}

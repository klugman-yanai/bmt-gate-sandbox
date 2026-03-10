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
    GCS_BUCKET           = var.gcs_bucket
    BMT_REPO_ROOT        = var.bmt_repo_root
    "startup-script"     = local.startup_script
    "startup-script-url" = ""
    bmt_image_family     = var.image_family
    bmt_image_version    = local.resolved_image
    bmt_managed_by       = "terraform"
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

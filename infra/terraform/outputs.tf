# Outputs consumed by tools/terraform_repo_vars.py (TERRAFORM_OUTPUT_TO_VAR).
# Run: just terraform-export-vars or just terraform-export-vars-apply.

output "gcs_bucket" {
  description = "GCS bucket for BMT (GCS_BUCKET)"
  value       = var.gcs_bucket
}

output "gcp_project" {
  description = "GCP project ID (GCP_PROJECT)"
  value       = var.gcp_project
}

output "gcp_zone" {
  description = "GCP zone for the BMT VM (GCP_ZONE)"
  value       = var.gcp_zone
}

output "bmt_vm_name" {
  description = "BMT VM instance name (BMT_LIVE_VM); set from Terraform only—do not set manually"
  value       = var.bmt_vm_name
}

output "bmt_repo_root" {
  description = "Path on VM where BMT runtime is installed (BMT_REPO_ROOT)"
  value       = var.bmt_repo_root
}

output "service_account" {
  description = "Service account email for VM/CI (GCP_SA_EMAIL)"
  value       = var.service_account
}

output "pubsub_subscription" {
  description = "Pub/Sub subscription ID for VM trigger delivery (BMT_PUBSUB_SUBSCRIPTION)"
  value       = google_pubsub_subscription.bmt_vm.name
}

output "pubsub_topic" {
  description = "Pub/Sub topic for CI to publish triggers to (BMT_PUBSUB_TOPIC)"
  value       = google_pubsub_topic.bmt_triggers.name
}

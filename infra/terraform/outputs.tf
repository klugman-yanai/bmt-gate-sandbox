output "vm_name" {
  description = "Name of the BMT VM (set this as the BMT_VM_NAME GitHub repo variable)"
  value       = google_compute_instance.bmt_vm.name
}

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
  description = "BMT VM instance name (BMT_VM_NAME)"
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

output "bmt_status_context" {
  description = "GitHub status check context (BMT_STATUS_CONTEXT)"
  value       = var.bmt_status_context
}

output "bmt_handshake_timeout_sec" {
  description = "Handshake timeout seconds (BMT_HANDSHAKE_TIMEOUT_SEC)"
  value       = var.bmt_handshake_timeout_sec
}

output "bmt_projects" {
  description = "BMT projects filter (BMT_PROJECTS)"
  value       = var.bmt_projects
}

output "bmt_runtime_context" {
  description = "BMT runtime context label (BMT_RUNTIME_CONTEXT)"
  value       = var.bmt_runtime_context
}

output "bmt_trigger_stale_sec" {
  description = "Trigger stale threshold seconds (BMT_TRIGGER_STALE_SEC)"
  value       = var.bmt_trigger_stale_sec
}

output "bmt_trigger_metadata_keep_recent" {
  description = "Trigger metadata keep recent count (BMT_TRIGGER_METADATA_KEEP_RECENT)"
  value       = var.bmt_trigger_metadata_keep_recent
}

output "vm_self_link" {
  description = "Self-link of the BMT VM instance"
  value       = google_compute_instance.bmt_vm.self_link
}

output "resolved_image" {
  description = "Image used for this VM (pinned name or resolved from family)"
  value       = local.resolved_image
}

output "image_family" {
  description = "Image family the VM was created from"
  value       = var.image_family
}

output "pubsub_subscription" {
  description = "Pub/Sub subscription ID for VM trigger delivery (pass as BMT_PUBSUB_SUBSCRIPTION)"
  value       = google_pubsub_subscription.bmt_vm.name
}

output "pubsub_topic" {
  description = "Pub/Sub topic for CI to publish triggers to"
  value       = google_pubsub_topic.bmt_triggers.name
}

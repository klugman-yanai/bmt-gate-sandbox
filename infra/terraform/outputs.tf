output "gcs_bucket"   { value = var.gcs_bucket }
output "gcp_project"  { value = var.gcp_project }
output "gcp_zone"     { value = var.gcp_zone }
output "bmt_vm_name"  { value = var.bmt_vm_name }
output "bmt_repo_root" { value = var.bmt_repo_root }
output "service_account" { value = var.service_account }
output "pubsub_subscription" { value = google_pubsub_subscription.bmt_vm.name }
output "pubsub_topic" { value = google_pubsub_topic.bmt_triggers.name }
output "bmt_vm_pool" {
  value = local.is_blue_green ? "${local.bmt_vm_base}-blue,${local.bmt_vm_base}-green" : ""
}

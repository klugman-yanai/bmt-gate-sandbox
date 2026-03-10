output "vm_name" {
  description = "Name of the BMT VM (set this as the BMT_VM_NAME GitHub repo variable)"
  value       = google_compute_instance.bmt_vm.name
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

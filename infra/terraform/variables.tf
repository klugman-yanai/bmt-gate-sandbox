variable "gcp_project" {
  type        = string
  description = "GCP project ID"
}

variable "gcp_zone" {
  type        = string
  description = "GCP zone for the BMT VM"
}

variable "gcs_bucket" {
  type        = string
  description = "GCS bucket for BMT runtime artifacts"
}

variable "bmt_vm_name" {
  type        = string
  description = "Name of the BMT VM instance"
}

variable "image_family" {
  type        = string
  default     = "bmt-runtime"
  description = "Compute image family to resolve latest image from"
}

variable "image_name" {
  type        = string
  default     = ""
  description = "Explicit image name; overrides image_family if set (use for pinning)"
}

variable "machine_type" {
  type        = string
  default     = "n2-standard-8"
  description = "Compute Engine machine type"
}

variable "service_account" {
  type        = string
  description = "Service account email for the VM"
}

variable "scopes" {
  type        = list(string)
  default     = ["https://www.googleapis.com/auth/cloud-platform"]
  description = "OAuth scopes for the VM service account"
}

variable "network" {
  type        = string
  default     = "default"
  description = "VPC network name"
}

variable "subnetwork" {
  type        = string
  default     = ""
  description = "Subnetwork name; empty uses the default for the network"
}

variable "tags" {
  type        = list(string)
  default     = []
  description = "Network tags applied to the VM"
}

variable "disk_size_gb" {
  type        = number
  default     = 100
  description = "Boot disk size in GB"
}

variable "disk_type" {
  type        = string
  default     = "pd-ssd"
  description = "Boot disk type"
}

variable "bmt_repo_root" {
  type        = string
  default     = "/opt/bmt"
  description = "Path on the VM where the BMT runtime is installed"
}

variable "startup_wrapper_script_path" {
  type        = string
  description = "Local path to the startup_wrapper.sh to inline as instance metadata"
}

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
  default     = "bmt-gate-blue"
  description = "Name of the BMT VM instance — blue in blue/green (exported as BMT_LIVE_VM); green is <base>-green. Override in terraform.tfvars if needed."
}

variable "image_family" {
  type        = string
  default     = "bmt-runtime"
  description = "Compute image family to resolve latest image from (default must match gcp/image/config/constants.py DEFAULT_IMAGE_FAMILY)"
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

# Path on VM where BMT runtime is installed. Default must match gcp/image/config/bmt_config.py DEFAULT_REPO_ROOT.
variable "bmt_repo_root" {
  type        = string
  default     = "/opt/bmt"
  description = "Path on the VM where the BMT runtime is installed (BMT_REPO_ROOT)"
}

variable "startup_wrapper_script_path" {
  type        = string
  default     = "../../.github/bmt/ci/resources/startup_entrypoint.sh"
  description = "Local path to the startup_entrypoint.sh to inline as instance metadata (relative to infra/terraform)"
}

# Default must match gcp/image/config/bmt_config.py BmtConfig.bmt_status_context.
variable "bmt_status_context" {
  type        = string
  default     = "BMT Gate"
  description = "GitHub status check context name (BMT_STATUS_CONTEXT)"
}

# Default must match gcp/image/config/bmt_config.py BmtConfig.bmt_handshake_timeout_sec (not exported to repo vars; constant in code).
variable "bmt_handshake_timeout_sec" {
  type        = number
  default     = 420
  description = "Handshake timeout in seconds (BMT_HANDSHAKE_TIMEOUT_SEC)"
}

variable "bmt_trigger_stale_sec" {
  type        = number
  default     = 900
  description = "Trigger stale threshold seconds (BMT_TRIGGER_STALE_SEC)"
}

variable "bmt_projects" {
  type        = string
  default     = ""
  description = "Path or identifier for BMT projects config (e.g. bmt_projects.json); exported for repo vars when set"
}

variable "bmt_runtime_context" {
  type        = string
  default     = "BMT Runtime"
  description = "Runtime context label (BMT_RUNTIME_CONTEXT); keep in sync with gcp/image/config/bmt_config.py DEFAULT_RUNTIME_CONTEXT"
}

variable "bmt_trigger_metadata_keep_recent" {
  type        = number
  default     = 2
  description = "Number of recent trigger metadata entries to keep (BMT_TRIGGER_METADATA_KEEP_RECENT); keep in sync with gcp/image/config/bmt_config.py TRIGGER_METADATA_KEEP_RECENT"
}

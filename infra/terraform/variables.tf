# Required (no default). Set in bmt.tfvars.json.
variable "gcp_project"   { type = string }
variable "gcp_zone"      { type = string }
variable "gcs_bucket"    { type = string }
variable "service_account" { type = string }

# Optional (have defaults).
variable "bmt_vm_name" {
  type    = string
  default = "bmt-gate-blue"
}

variable "image_family" {
  type    = string
  default = "bmt-runtime"
}

variable "image_name" {
  type    = string
  default = ""
}

variable "machine_type" {
  type    = string
  default = "n2-standard-8"
}

variable "scopes" {
  type    = list(string)
  default = ["https://www.googleapis.com/auth/cloud-platform"]
}

variable "network" {
  type    = string
  default = "default"
}

variable "subnetwork" {
  type    = string
  default = ""
}

variable "tags" {
  type    = list(string)
  default = []
}

variable "disk_size_gb" {
  type    = number
  default = 100
}

variable "disk_type" {
  type    = string
  default = "pd-ssd"
}

variable "bmt_repo_root" {
  type    = string
  default = "/opt/bmt"
}

variable "startup_wrapper_script_path" {
  type    = string
  default = "../../.github/bmt/ci/resources/startup_entrypoint.sh"
}

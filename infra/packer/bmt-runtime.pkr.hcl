packer {
  required_version = ">= 1.10.0"
  required_plugins {
    googlecompute = {
      source  = "github.com/hashicorp/googlecompute"
      version = ">= 1.1.0"
    }
  }
}

# ---------------------------------------------------------------------------
# Variables — override via -var or a .pkrvars.hcl file
# ---------------------------------------------------------------------------

variable "gcp_project" { type = string }
variable "gcp_zone" { type = string }
variable "gcs_bucket" { type = string }

variable "image_family" {
  type    = string
  default = "bmt-runtime"
}

variable "base_image_family" {
  type    = string
  default = "ubuntu-2204-lts"
}

variable "base_image_project" {
  type    = string
  default = "ubuntu-os-cloud"
}

variable "machine_type" {
  type    = string
  default = "e2-standard-4"
}

variable "service_account" {
  type    = string
  default = ""
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

variable "bmt_repo_root" {
  type    = string
  default = "/opt/bmt"
}

variable "keep_builder" {
  type    = bool
  default = false
}

# ---------------------------------------------------------------------------
# Locals
# ---------------------------------------------------------------------------

locals {
  timestamp  = formatdate("YYYYMMDD-HHmmss", timestamp())
  image_name = "${var.image_family}-${local.timestamp}"
}

# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

source "googlecompute" "bmt_runtime" {
  project_id   = var.gcp_project
  zone         = var.gcp_zone
  machine_type = var.machine_type

  source_image_family  = var.base_image_family
  source_image_project = var.base_image_project

  image_name        = local.image_name
  image_family      = var.image_family
  image_description = "BMT runtime image baked from gs://${var.gcs_bucket}/code"
  image_labels = {
    bmt-image-family   = replace(lower(var.image_family), "_", "-")
    bmt-image-version  = replace(lower(local.image_name), "_", "-")
    bmt-bake-timestamp = local.timestamp
  }

  service_account_email = var.service_account != "" ? var.service_account : null
  network               = var.network
  subnetwork            = var.subnetwork != "" ? var.subnetwork : null
  tags                  = var.tags

  disk_size = 50
  disk_type = "pd-ssd"

  ssh_username = "packer"

  # Packer cleans up the builder VM automatically; no manual trap needed.
  skip_create_image = false
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

build {
  name    = "bmt-runtime"
  sources = ["source.googlecompute.bmt_runtime"]

  # 1. Sync code snapshot from GCS
  provisioner "shell" {
    inline = [
      "set -euo pipefail",
      "sudo apt-get install -y -q google-cloud-cli-gke-gcloud-auth-plugin 2>/dev/null || true",
      "sudo rm -rf ${var.bmt_repo_root}",
      "sudo mkdir -p ${var.bmt_repo_root}",
      "sudo gcloud storage rsync gs://${var.gcs_bucket}/code ${var.bmt_repo_root} --recursive",
      "sudo chmod +x ${var.bmt_repo_root}/_tools/uv/linux-x86_64/uv || true",
    ]
  }

  # 2. Install Google Cloud Ops Agent
  provisioner "shell" {
    inline = [
      "set -euo pipefail",
      "curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh",
      "sudo bash add-google-cloud-ops-agent-repo.sh --also-install",
      "rm -f add-google-cloud-ops-agent-repo.sh",
    ]
  }

  # 3. Install Python and VM dependencies via uv
  provisioner "shell" {
    inline = [
      "set -euo pipefail",
      "UV_BIN=${var.bmt_repo_root}/_tools/uv/linux-x86_64/uv",
      "sudo \"$UV_BIN\" python install 3.12",
      "sudo BMT_UV_BIN=\"$UV_BIN\" bash ${var.bmt_repo_root}/bootstrap/install_deps.sh ${var.bmt_repo_root}",
    ]
  }

  # 4. Write image manifest (used by SLSA provenance and vm_watcher startup verification)
  provisioner "shell" {
    inline = [
      "set -euo pipefail",
      "sudo python3 - <<'PY'",
      "import hashlib, json",
      "from datetime import datetime, timezone",
      "from pathlib import Path",
      "repo = Path('${var.bmt_repo_root}')",
      "def digest(p):",
      "    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ''",
      "manifest = {",
      "    'bake_timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),",
      "    'image_family': '${var.image_family}',",
      "    'image_source': {'bucket': '${var.gcs_bucket}', 'code_prefix': 'code/'},",
      "    'deps_fingerprint': hashlib.sha256((digest(repo/'pyproject.toml')+digest(repo/'uv.lock')).encode()).hexdigest(),",
      "    'pyproject_sha256': digest(repo/'pyproject.toml'),",
      "    'uv_lock_sha256': digest(repo/'uv.lock'),",
      "    'uv_binary_sha256': digest(repo/'_tools/uv/linux-x86_64/uv'),",
      "}",
      "(repo/'.image_manifest.json').write_text(json.dumps(manifest, indent=2)+'\\n', encoding='utf-8')",
      "PY",
    ]
  }

  # 5. Upload manifest to GCS so SLSA provenance generator can reference it
  provisioner "shell" {
    inline = [
      "gcloud storage cp ${var.bmt_repo_root}/.image_manifest.json gs://${var.gcs_bucket}/provenance/image-manifests/${local.image_name}.json",
    ]
  }

  post-processor "manifest" {
    output     = "infra/packer/manifest.json"
    strip_path = true
  }
}

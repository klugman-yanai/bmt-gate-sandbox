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

  # 3. Install Python 3.12 and VM dependencies into a pre-baked venv.
  #    Uses pip directly (no uv dependency at runtime; uv is only needed during image build if desired).
  provisioner "shell" {
    inline = [
      "set -euo pipefail",
      # Ensure Python 3.12 is available (Ubuntu 22.04 ships 3.10 by default).
      "sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true",
      "sudo apt-get update -q",
      "sudo apt-get install -y -q python3.12 python3.12-venv python3.12-dev",
      # Create the pre-baked venv.
      "sudo python3.12 -m venv ${var.bmt_repo_root}/.venv",
      "sudo ${var.bmt_repo_root}/.venv/bin/pip install --quiet --upgrade pip",
      # Install exact deps matching pyproject.toml vm extras.
      "sudo ${var.bmt_repo_root}/.venv/bin/pip install --quiet httpx>=0.27 'google-cloud-storage>=2.16' 'google-cloud-pubsub>=2.21' 'PyJWT>=2.0' 'cryptography>=41.0'",
      # Verify imports.
      "sudo ${var.bmt_repo_root}/.venv/bin/python -c \"import jwt, cryptography, httpx, google.cloud.storage, google.cloud.pubsub_v1; print('OK')\"",
      # Write fingerprint so startup_example.sh skips dep install on first boot.
      "sudo bash -c \"sha256sum ${var.bmt_repo_root}/pyproject.toml ${var.bmt_repo_root}/uv.lock 2>/dev/null | sha256sum | awk '{print \\$1}' > ${var.bmt_repo_root}/.venv/.bmt_dep_fingerprint || true\"",
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

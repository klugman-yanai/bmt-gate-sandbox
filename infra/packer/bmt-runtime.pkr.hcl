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

  source_image_family       = var.base_image_family
  source_image_project_id   = [var.base_image_project]

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

  # Ubuntu 22.04 base image uses 'ubuntu', not 'packer'.
  ssh_username = "ubuntu"

  # Packer cleans up the builder VM automatically; no manual trap needed.
  skip_create_image = false
}

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
# Build contract: (1) Sync code from GCS to bmt_repo_root, (2) record glibc for manifest,
# (3) install Google Cloud Ops Agent, (4) install Python 3.12 and deps from vm/vm_deps.txt,
# (5) write image manifest, (6) upload manifest to GCS, (7) cloud-init clean. Any provisioner failure fails the build.
# (1b) Install ffmpeg and gcsfuse; (1c) create /mnt/audio_data for FUSE mount.
# ---------------------------------------------------------------------------

build {
  name    = "bmt-runtime"
  sources = ["source.googlecompute.bmt_runtime"]

  # 1. Install gcloud CLI (if missing) and sync code snapshot from GCS
  provisioner "shell" {
    execute_command = "chmod +x {{.Path}}; {{.Vars}} bash {{.Path}}"
    inline = [
      "set -euo pipefail",
      # Ensure Google Cloud CLI is available (Ubuntu 22.04 base may not have it).
      "if ! command -v gcloud >/dev/null 2>&1; then",
      "  sudo apt-get update -qq",
      "  sudo apt-get install -y -qq apt-transport-https ca-certificates gnupg curl",
      "  echo 'deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main' | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list",
      "  curl -sSf https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg",
      "  sudo apt-get update -qq && sudo apt-get install -y -qq google-cloud-cli",
      "fi",
      "sudo apt-get install -y -q google-cloud-cli-gke-gcloud-auth-plugin 2>/dev/null || true",
      "sudo rm -rf ${var.bmt_repo_root}",
      "sudo mkdir -p ${var.bmt_repo_root}",
      "sudo gcloud storage rsync gs://${var.gcs_bucket}/code ${var.bmt_repo_root} --recursive",
    ]
  }

  # 1b. Install ffmpeg and gcsfuse (for hybrid storage / FUSE dataset mount)
  provisioner "shell" {
    execute_command = "chmod +x {{.Path}}; {{.Vars}} bash {{.Path}}"
    inline = [
      "set -euo pipefail",
      "export DEBIAN_FRONTEND=noninteractive",
      "sudo apt-get update -qq",
      "sudo apt-get install -y -qq ffmpeg curl gnupg",
      "export GCSFUSE_REPO=gcsfuse-$(lsb_release -c -s)",
      "echo \"deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt $GCSFUSE_REPO main\" | sudo tee /etc/apt/sources.list.d/gcsfuse.list",
      "curl -sSf https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg",
      "sudo apt-get update -qq",
      "sudo apt-get install -y -qq gcsfuse",
      "sudo mkdir -p /mnt/audio_data",
      "sudo chown -R ubuntu:ubuntu /mnt/audio_data",
    ]
  }

  # 2. Record glibc version for manifest.
  provisioner "shell" {
    execute_command = "chmod +x {{.Path}}; {{.Vars}} bash {{.Path}}"
    inline = [
      "set -euo pipefail",
      "GLIBC_VERSION_RAW=$(ldd --version 2>/dev/null | head -n1 || true)",
      "printf 'GLIBC_VERSION=%s\\n' \"$GLIBC_VERSION_RAW\" | sudo tee /tmp/bmt-image-build-meta.env >/dev/null",
    ]
  }

  # 3. Install Google Cloud Ops Agent
  provisioner "shell" {
    execute_command = "chmod +x {{.Path}}; {{.Vars}} bash {{.Path}}"
    inline = [
      "set -euo pipefail",
      "curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh",
      "sudo bash add-google-cloud-ops-agent-repo.sh --also-install",
      "rm -f add-google-cloud-ops-agent-repo.sh",
    ]
  }

  # 4. Install Python 3.12 and VM dependencies into a pre-baked venv.
  #    Deps from scripts/vm_deps.txt (single source of truth; sync code already in place).
  provisioner "shell" {
    execute_command  = "chmod +x {{.Path}}; {{.Vars}} bash {{.Path}}"
    environment_vars = ["DEBIAN_FRONTEND=noninteractive"]
    inline = [
      "set -euo pipefail",
      # Ensure Python 3.12 is available (Ubuntu 22.04 ships 3.10 by default).
      "sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true",
      "sudo apt-get update -q",
      "sudo apt-get install -y -q python3.12 python3.12-venv python3.12-dev",
      # Create the pre-baked venv.
      "sudo python3.12 -m venv ${var.bmt_repo_root}/.venv",
      "sudo ${var.bmt_repo_root}/.venv/bin/pip install --quiet --upgrade pip",
      "sudo ${var.bmt_repo_root}/.venv/bin/pip install --quiet -r ${var.bmt_repo_root}/scripts/vm_deps.txt",
      # Verify imports.
      "sudo ${var.bmt_repo_root}/.venv/bin/python -c \"import jwt, cryptography, httpx, google.cloud.storage, google.cloud.pubsub_v1; print('OK')\"",
    ]
  }

  # 5. Write image manifest (used by SLSA provenance and startup verification)
  provisioner "shell" {
    execute_command = "chmod +x {{.Path}}; {{.Vars}} bash {{.Path}}"
    inline = [
      "set -euo pipefail",
      "sudo python3 - <<'PY'",
      "import hashlib, json",
      "from datetime import datetime, timezone",
      "from pathlib import Path",
      "repo = Path('${var.bmt_repo_root}')",
      "build_meta = {}",
      "meta_path = Path('/tmp/bmt-image-build-meta.env')",
      "if meta_path.exists():",
      "    for line in meta_path.read_text(encoding='utf-8').splitlines():",
      "        if '=' not in line:",
      "            continue",
      "        key, value = line.split('=', 1)",
      "        build_meta[key.strip()] = value.strip()",
      "def digest(p):",
      "    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ''",
      "manifest = {",
      "    'bake_timestamp_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),",
      "    'image_family': '${var.image_family}',",
      "    'base_image_family': '${var.base_image_family}',",
      "    'base_image_project': '${var.base_image_project}',",
      "    'image_source': {'bucket': '${var.gcs_bucket}', 'code_prefix': 'code/'},",
      "    'deps_fingerprint': digest(repo/'pyproject.toml'),",
      "    'pyproject_sha256': digest(repo/'pyproject.toml'),",
      "    'glibc_version': build_meta.get('GLIBC_VERSION', ''),",
      "}",
      "(repo/'.image_manifest.json').write_text(json.dumps(manifest, indent=2)+'\\n', encoding='utf-8')",
      "PY",
    ]
  }

  # 6. Upload manifest to GCS so SLSA provenance generator can reference it
  provisioner "shell" {
    inline = [
      "sudo gcloud storage cp ${var.bmt_repo_root}/.image_manifest.json gs://${var.gcs_bucket}/provenance/image-manifests/${local.image_name}.json",
    ]
  }

  # 7. Reset cloud-init state before image capture.
  #    Prevents cloned VMs from inheriting stale cloud-init status that can
  #    delay or block startup-script execution sequencing.
  provisioner "shell" {
    execute_command = "chmod +x {{.Path}}; {{.Vars}} bash {{.Path}}"
    inline = [
      "set -euo pipefail",
      "if command -v cloud-init >/dev/null 2>&1; then sudo cloud-init clean --logs --machine-id || sudo cloud-init clean --logs; fi",
    ]
  }

  post-processor "manifest" {
    output     = "infra/packer/manifest.json"
    strip_path = true
  }
}

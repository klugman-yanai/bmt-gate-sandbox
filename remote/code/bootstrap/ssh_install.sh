#!/usr/bin/env bash
# SSH into the BMT VM and run dependency install (uv sync --extra vm) so deps are
# persistent on the VM's disk across stop/start. Run from your laptop; requires gcloud.
#
# Set (or export) before running (required: GCP_PROJECT, GCP_ZONE, BMT_VM_NAME):
#   GCP_PROJECT   - GCP project ID
#   GCP_ZONE      - VM zone (e.g. europe-west4-a)
#   BMT_VM_NAME   - VM instance name
#   GCS_BUCKET    - GCS bucket name (required when vm image does not already have uv)
#   BMT_REPO_ROOT - Path to repo on the VM (default: /opt/bmt)
#   BMT_BUCKET_PREFIX - Optional parent bucket prefix
#
# Example:
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-vm GCS_BUCKET=my-bucket
#   ./remote/code/bootstrap/ssh_install.sh

set -euo pipefail

BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
GCS_BUCKET="${GCS_BUCKET:-}"
BMT_BUCKET_PREFIX="${BMT_BUCKET_PREFIX:-}"
GCP_PROJECT="${GCP_PROJECT:-}"
GCP_ZONE="${GCP_ZONE:-}"
BMT_VM_NAME="${BMT_VM_NAME:-}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
  echo "Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET." >&2
  echo "Example: GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-vm GCS_BUCKET=my-bucket $0" >&2
  exit 1
fi

# Resolve uv on VM (local override/PATH/pinned code artifact), then sync deps into persistent .venv.
gcloud compute ssh "$BMT_VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  -- \
  "set -euo pipefail; \
   cd '${BMT_REPO_ROOT}'; \
   export GCS_BUCKET='${GCS_BUCKET}' BMT_BUCKET_PREFIX='${BMT_BUCKET_PREFIX}' BMT_REPO_ROOT='${BMT_REPO_ROOT}'; \
   source ./bootstrap/ensure_uv.sh; \
   ./bootstrap/install_deps.sh '${BMT_REPO_ROOT}'"

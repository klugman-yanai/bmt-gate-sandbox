#!/usr/bin/env bash
# One-time setup: set VM custom metadata and startup script from GH variables so
# the VM runs the watcher on every boot. Run from your laptop (same env as CI
# vars: GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_VM_NAME).
#
# Prerequisites:
#   - Repo (and uv deps) already on the VM at BMT_REPO_ROOT (e.g. /opt/bmt).
#   - VM service account has roles/secretmanager.secretAccessor for GitHub App secrets.
#
# Set (or export) before running (required: GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, GCS_BUCKET):
#   GCP_PROJECT   - GCP project ID
#   GCP_ZONE      - VM zone (e.g. europe-west4-a)
#   BMT_VM_NAME   - VM instance name
#   GCS_BUCKET    - GCS bucket name (same as GitHub variable)
#   BMT_BUCKET_PREFIX - Optional bucket prefix (default empty)
#   BMT_REPO_ROOT - Path to repo on the VM (default: /opt/bmt)
#
# Example (match your GitHub Actions variables):
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-vm GCS_BUCKET=my-bmt-bucket
#   ./remote/bootstrap/setup_vm_startup.sh

set -euo pipefail

BMT_VM_NAME="${BMT_VM_NAME:-}"
GCP_ZONE="${GCP_ZONE:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
GCP_PROJECT="${GCP_PROJECT:-}"

BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
BMT_BUCKET_PREFIX="${BMT_BUCKET_PREFIX:-}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
  echo "Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET." >&2
  echo "Optional: BMT_BUCKET_PREFIX, BMT_REPO_ROOT." >&2
  echo "Example: GCP_PROJECT=p GCP_ZONE=z BMT_VM_NAME=v GCS_BUCKET=b $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${SCRIPT_DIR}/startup_wrapper.sh"
if [[ ! -f "$WRAPPER" ]]; then
  echo "Missing startup_wrapper.sh at $WRAPPER" >&2
  exit 1
fi

echo "Setting VM metadata and startup script for $BMT_VM_NAME (bucket=$GCS_BUCKET prefix=${BMT_BUCKET_PREFIX:-<none>})..."
gcloud compute instances add-metadata "$BMT_VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  --metadata "GCS_BUCKET=${GCS_BUCKET},BMT_BUCKET_PREFIX=${BMT_BUCKET_PREFIX},BMT_REPO_ROOT=${BMT_REPO_ROOT}" \
  --metadata-from-file "startup-script=${WRAPPER}"

echo "Done. On next boot the VM will run the startup script (deps, Secret Manager, watcher)."
echo "To apply immediately without rebooting, SSH in and run: sudo /opt/bmt/remote/bootstrap/startup_example.sh"

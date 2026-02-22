#!/usr/bin/env bash
# One-time setup: set VM custom metadata and startup script from GH variables so
# the VM runs the watcher on every boot. Run from your laptop (same env as CI
# vars: GCS_BUCKET; and GCP_PROJECT or GCP_SA_EMAIL, GCP_ZONE, VM_NAME).
#
# Prerequisites:
#   - Repo (and uv deps) already on the VM at BMT_REPO_ROOT (e.g. /opt/bmt).
#   - VM service account has roles/secretmanager.secretAccessor for GitHub App secrets.
#
# Set (or export) before running (required: GCP_ZONE, VM_NAME, GCS_BUCKET; GCP_PROJECT or GCP_SA_EMAIL):
#   GCP_PROJECT   - GCP project ID (optional if GCP_SA_EMAIL set; derived from SA email)
#   GCP_SA_EMAIL  - Service account email (used to derive GCP_PROJECT when unset)
#   GCP_ZONE      - VM zone (e.g. europe-west4-a)
#   VM_NAME       - VM instance name (or BMT_VM_NAME)
#   GCS_BUCKET    - GCS bucket name (same as GitHub variable)
#   BMT_BUCKET_PREFIX - Optional bucket prefix (default empty)
#   BMT_REPO_ROOT - Path to repo on the VM (default: /opt/bmt)
#
# Example (match your GitHub Actions variables):
#   export GCP_SA_EMAIL=... GCP_ZONE=europe-west4-a VM_NAME=bmt-vm GCS_BUCKET=my-bmt-bucket
#   ./remote/bootstrap/setup_vm_startup.sh

set -euo pipefail

VM_NAME="${VM_NAME:-${BMT_VM_NAME:-}}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
BMT_BUCKET_PREFIX="${BMT_BUCKET_PREFIX:-}"

# Derive GCP_PROJECT from GCP_SA_EMAIL when unset
if [[ -z "${GCP_PROJECT:-}" && -n "${GCP_SA_EMAIL:-}" ]]; then
  if [[ "${GCP_SA_EMAIL}" =~ @(.+)\.iam\.gserviceaccount\.com ]]; then
    GCP_PROJECT="${BASH_REMATCH[1]}"
  fi
fi

if [[ -z "${GCP_PROJECT:-}" || -z "${GCP_ZONE:-}" || -z "${VM_NAME:-}" || -z "${GCS_BUCKET:-}" ]]; then
  echo "Set GCP_ZONE, VM_NAME (or BMT_VM_NAME), GCS_BUCKET, and GCP_PROJECT or GCP_SA_EMAIL." >&2
  echo "Optional: BMT_BUCKET_PREFIX, BMT_REPO_ROOT." >&2
  echo "Example: GCP_SA_EMAIL=... GCP_ZONE=z VM_NAME=v GCS_BUCKET=b $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${SCRIPT_DIR}/startup_wrapper.sh"
if [[ ! -f "$WRAPPER" ]]; then
  echo "Missing startup_wrapper.sh at $WRAPPER" >&2
  exit 1
fi

echo "Setting VM metadata and startup script for $VM_NAME (bucket=$GCS_BUCKET prefix=${BMT_BUCKET_PREFIX:-<none>})..."
gcloud compute instances add-metadata "$VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  --metadata "GCS_BUCKET=${GCS_BUCKET},BMT_BUCKET_PREFIX=${BMT_BUCKET_PREFIX},BMT_REPO_ROOT=${BMT_REPO_ROOT}" \
  --metadata-from-file "startup-script=${WRAPPER}"

echo "Done. On next boot the VM will run the startup script (deps, Secret Manager, watcher)."
echo "To apply immediately without rebooting, SSH in and run: sudo /opt/bmt/remote/bootstrap/startup_example.sh"

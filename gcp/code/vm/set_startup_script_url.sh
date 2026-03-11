#!/usr/bin/env bash
# One-time setup: set VM metadata so startup-script-url points at the GCS-hosted
# entrypoint under code/bootstrap/startup_entrypoint.sh. Run from your laptop (same env as CI
# vars: GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_VM_NAME).
#
# Prerequisites:
#   - code namespace in bucket is synced (just sync-remote && just verify-sync).
#   - VM service account has roles/secretmanager.secretAccessor for GitHub App secrets.
#
# Set (or export) before running (required: GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, GCS_BUCKET):
#   GCP_PROJECT   - GCP project ID
#   GCP_ZONE      - VM zone (e.g. europe-west4-a)
#   BMT_VM_NAME   - VM instance name
#   GCS_BUCKET    - GCS bucket name (same as GitHub variable)
#   BMT_REPO_ROOT - Path to repo on the VM (default: /opt/bmt)
#
# Example (match your GitHub Actions variables):
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-vm GCS_BUCKET=my-bmt-bucket
#   ./gcp/code/bootstrap/set_startup_script_url.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/shared.sh"
_bmt_log_tag="set_startup_script_url"

BMT_VM_NAME="${BMT_VM_NAME:-}"
GCP_ZONE="${GCP_ZONE:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
GCP_PROJECT="${GCP_PROJECT:-}"

BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
  _log_err "::error::Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET."
  _log_err "Optional: BMT_REPO_ROOT. Example: GCP_PROJECT=p GCP_ZONE=z BMT_VM_NAME=v GCS_BUCKET=b $0"
  exit 1
fi

ENTRYPOINT_URL="gs://${GCS_BUCKET}/code/bootstrap/startup_entrypoint.sh"
_log "Checking entrypoint at ${ENTRYPOINT_URL}..."
if ! gcloud storage ls "${ENTRYPOINT_URL}" >/dev/null 2>&1; then
  _log_err "::error::Could not find startup entrypoint at: ${ENTRYPOINT_URL}"
  _log_err "Sync code first: just sync-gcp && just verify-sync"
  exit 1
fi

_log "Setting VM metadata and startup-script-url for ${BMT_VM_NAME} (bucket=${GCS_BUCKET})..."
gcloud compute instances add-metadata "$BMT_VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  --metadata "GCS_BUCKET=${GCS_BUCKET},BMT_REPO_ROOT=${BMT_REPO_ROOT},startup-script=,startup-script-url=${ENTRYPOINT_URL}"

_log "Done. On next boot the VM will run startup from ${ENTRYPOINT_URL}."
_log "Rollback: ./gcp/code/bootstrap/rollback_startup_to_inline.sh"

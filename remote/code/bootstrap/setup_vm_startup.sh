#!/usr/bin/env bash
# One-time setup: set VM metadata so startup-script-url points at the GCS-hosted
# wrapper under code/bootstrap/startup_wrapper.sh. Run from your laptop (same env as CI
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
#   BMT_BUCKET_PREFIX - Optional bucket prefix (default empty)
#   BMT_REPO_ROOT - Path to repo on the VM (default: /opt/bmt)
#
# Example (match your GitHub Actions variables):
#   export GCP_PROJECT=... GCP_ZONE=europe-west4-a BMT_VM_NAME=bmt-vm GCS_BUCKET=my-bmt-bucket
#   ./remote/code/bootstrap/setup_vm_startup.sh

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

PARENT_PREFIX="${BMT_BUCKET_PREFIX#/}"
PARENT_PREFIX="${PARENT_PREFIX%/}"
CODE_PREFIX="code"
if [[ -n "${PARENT_PREFIX}" ]]; then
  CODE_PREFIX="${PARENT_PREFIX}/code"
fi
CODE_WRAPPER_URL="gs://${GCS_BUCKET}/${CODE_PREFIX}/bootstrap/startup_wrapper.sh"
if ! gcloud storage ls "${CODE_WRAPPER_URL}" >/dev/null 2>&1; then
  echo "Could not find startup wrapper at:" >&2
  echo "  - ${CODE_WRAPPER_URL}" >&2
  echo "Sync code first: just sync-remote && just verify-sync" >&2
  exit 1
fi

echo "Setting VM metadata and startup-script-url for $BMT_VM_NAME (bucket=$GCS_BUCKET prefix=${BMT_BUCKET_PREFIX:-<none>})..."
gcloud compute instances add-metadata "$BMT_VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  --metadata "GCS_BUCKET=${GCS_BUCKET},BMT_BUCKET_PREFIX=${BMT_BUCKET_PREFIX},BMT_REPO_ROOT=${BMT_REPO_ROOT},startup-script=,startup-script-url=${CODE_WRAPPER_URL}"

echo "Done. On next boot the VM will sync code from ${CODE_WRAPPER_URL} and run watcher."
echo "Rollback path: ./remote/code/bootstrap/rollback_vm_startup_to_inline.sh"

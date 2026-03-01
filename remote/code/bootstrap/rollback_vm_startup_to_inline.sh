#!/usr/bin/env bash
# Roll back startup mode to inline startup-script metadata (legacy mode).
set -euo pipefail

BMT_VM_NAME="${BMT_VM_NAME:-}"
GCP_ZONE="${GCP_ZONE:-}"
GCP_PROJECT="${GCP_PROJECT:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
  echo "Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${SCRIPT_DIR}/startup_wrapper.sh"
if [[ ! -f "$WRAPPER" ]]; then
  echo "Missing startup_wrapper.sh at $WRAPPER" >&2
  exit 1
fi

echo "Rolling back $BMT_VM_NAME to inline startup-script mode..."
gcloud compute instances add-metadata "$BMT_VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  --metadata "GCS_BUCKET=${GCS_BUCKET},BMT_REPO_ROOT=${BMT_REPO_ROOT},startup-script-url=" \
  --metadata-from-file "startup-script=${WRAPPER}"

echo "Rollback metadata applied."

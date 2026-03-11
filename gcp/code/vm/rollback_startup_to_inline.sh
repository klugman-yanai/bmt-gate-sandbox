#!/usr/bin/env bash
# Roll back startup mode to inline startup-script metadata (legacy mode).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/shared.sh"
_bmt_log_tag="rollback_startup_to_inline"

BMT_VM_NAME="${BMT_VM_NAME:-}"
GCP_ZONE="${GCP_ZONE:-}"
GCP_PROJECT="${GCP_PROJECT:-}"
GCS_BUCKET="${GCS_BUCKET:-}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"

if [[ -z "$GCP_PROJECT" || -z "$GCP_ZONE" || -z "$BMT_VM_NAME" || -z "$GCS_BUCKET" ]]; then
  _log_err "::error::Set GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, and GCS_BUCKET."
  exit 1
fi

ENTRYPOINT="${SCRIPT_DIR}/startup_entrypoint.sh"
if [[ ! -f "$ENTRYPOINT" ]]; then
  _log_err "::error::Missing startup_entrypoint.sh at ${ENTRYPOINT}"
  exit 1
fi

_log "Rolling back ${BMT_VM_NAME} to inline startup-script (entrypoint=${ENTRYPOINT})..."
gcloud compute instances add-metadata "$BMT_VM_NAME" \
  --zone="$GCP_ZONE" \
  --project="$GCP_PROJECT" \
  --metadata "GCS_BUCKET=${GCS_BUCKET},BMT_REPO_ROOT=${BMT_REPO_ROOT},startup-script-url=" \
  --metadata-from-file "startup-script=${ENTRYPOINT}"

_log "Done. VM will use inline startup-script on next boot."

#!/usr/bin/env bash
# Cloud Run Job entrypoint: pull code from GCS then run vm_watcher.py in single-trigger mode.
set -euo pipefail

: "${GCS_BUCKET:?GCS_BUCKET must be set}"
: "${WORKFLOW_RUN_ID:?WORKFLOW_RUN_ID must be set}"

CODE_ROOT="gs://${GCS_BUCKET}/code"
LOCAL_CODE="/app/code"

echo "[entrypoint] Downloading BMT code from ${CODE_ROOT} …"
gcloud storage cp --recursive "${CODE_ROOT}/" "${LOCAL_CODE}/"

# Install Python dependencies if pyproject.toml is present
if [[ -f "${LOCAL_CODE}/pyproject.toml" ]]; then
    echo "[entrypoint] Installing Python dependencies …"
    uv pip install --system -e "${LOCAL_CODE}" --quiet
fi

echo "[entrypoint] Starting vm_watcher (single-trigger mode, workflow_run_id=${WORKFLOW_RUN_ID}) …"
exec python3 "${LOCAL_CODE}/vm_watcher.py" \
    --bucket "${GCS_BUCKET}" \
    --workflow-run-id "${WORKFLOW_RUN_ID}" \
    ${BMT_WORKSPACE_ROOT:+--workspace-root "${BMT_WORKSPACE_ROOT}"}

#!/usr/bin/env bash
# Startup entrypoint loaded from VM metadata startup-script.
# Immutable runtime contract: execute baked startup script from local disk only.
set -euo pipefail

_log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [entrypoint] $*"; }
_log_err() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [entrypoint] $*" >&2; }

BMT_REPO_ROOT_DEFAULT="/opt/bmt"
SCRIPTS_SUBDIR="scripts"
RUN_WATCHER_SCRIPT="run_watcher.py"
VALIDATE_SCRIPT="validate_bucket_contract.py"

_read_meta() {
  local key="$1"
  curl -sSf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/${key}" 2>/dev/null || true
}

_log "Reading VM metadata (GCS_BUCKET, BMT_REPO_ROOT)..."
export GCS_BUCKET="${GCS_BUCKET:-$(_read_meta "GCS_BUCKET")}"
export BMT_REPO_ROOT="${BMT_REPO_ROOT:-$(_read_meta "BMT_REPO_ROOT")}"
export BMT_DATASET_MOUNT_ENABLED="${BMT_DATASET_MOUNT_ENABLED:-$(_read_meta "BMT_DATASET_MOUNT_ENABLED")}"
export BMT_RESULTS_PREFIX="${BMT_RESULTS_PREFIX:-$(_read_meta "BMT_RESULTS_PREFIX")}"

GCS_BUCKET="${GCS_BUCKET:?Set metadata GCS_BUCKET}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-${BMT_REPO_ROOT_DEFAULT}}"
STARTUP_MAIN="${BMT_REPO_ROOT}/${SCRIPTS_SUBDIR}/${RUN_WATCHER_SCRIPT}"
VALIDATE_SCRIPT_PATH="${BMT_REPO_ROOT}/${SCRIPTS_SUBDIR}/${VALIDATE_SCRIPT}"

# Optional: mount dataset prefix via gcsfuse for hybrid storage (zero-disk streaming)
if [[ "${BMT_DATASET_MOUNT_ENABLED:-0}" == "1" ]]; then
  _log "Mounting dataset prefix with gcsfuse..."
  sudo mkdir -p /mnt/audio_data
  if ! gcsfuse --only-dir sk/inputs/false_rejects --implicit-dirs "${GCS_BUCKET}" /mnt/audio_data; then
    _log_err "::error::gcsfuse mount failed"
    exit 1
  fi
  _log "gcsfuse mount ready at /mnt/audio_data"
fi

# Eager code sync: pull latest code from GCS (overwrites baked snapshot)
_log "Pulling latest code from gs://${GCS_BUCKET}/code to ${BMT_REPO_ROOT}"
if ! gcloud storage rsync "gs://${GCS_BUCKET}/code" "${BMT_REPO_ROOT}" --recursive; then
  _log_err "::error::Code sync from GCS failed"
  exit 1
fi

# Contract validation: if bucket is missing required objects, self-destruct
if [[ -f "${VALIDATE_SCRIPT_PATH}" ]]; then
  _log "Running bucket contract validation..."
  if ! "${BMT_REPO_ROOT}/.venv/bin/python" "${VALIDATE_SCRIPT_PATH}"; then
    _log_err "::error::Bucket contract validation failed; shutting down"
    sudo poweroff || true
    exit 1
  fi
else
  _log "Validation script not found: ${VALIDATE_SCRIPT_PATH}; skipping"
fi

if [[ ! -f "${STARTUP_MAIN}" ]]; then
  _log_err "::error::Missing baked startup script: ${STARTUP_MAIN}"
  _log_err "::error::Rebuild/provision VM from the hardened pre-baked runtime image."
  exit 1
fi

_log "Executing ${STARTUP_MAIN}"
chmod +x "${STARTUP_MAIN}" 2>/dev/null || true
exec "${BMT_REPO_ROOT}/.venv/bin/python" "${STARTUP_MAIN}"

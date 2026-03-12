#!/usr/bin/env bash
# Startup entrypoint loaded from VM metadata startup-script.
# Immutable runtime contract: execute baked startup script from local disk only.
set -euo pipefail

_log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [entrypoint] $*"; }
_log_err() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [entrypoint] $*" >&2; }

_read_meta() {
	local key="$1"
	curl -sSf -H "Metadata-Flavor: Google" \
		"http://metadata.google.internal/computeMetadata/v1/instance/attributes/${key}" 2>/dev/null || true
}

_log "Reading VM metadata (GCS_BUCKET, BMT_REPO_ROOT)..."
export GCS_BUCKET="${GCS_BUCKET:-$(_read_meta "GCS_BUCKET")}"
export BMT_REPO_ROOT="${BMT_REPO_ROOT:-$(_read_meta "BMT_REPO_ROOT")}"

GCS_BUCKET="${GCS_BUCKET:?Set metadata GCS_BUCKET}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
STARTUP_MAIN="${BMT_REPO_ROOT}/vm/run_watcher.sh"

if [[ ! -f "${STARTUP_MAIN}" ]]; then
	_log_err "::error::Missing baked startup script: ${STARTUP_MAIN}"
	_log_err "::error::Rebuild/provision VM from the hardened pre-baked runtime image."
	exit 1
fi

_log "Executing ${STARTUP_MAIN}"
chmod +x "${STARTUP_MAIN}" 2>/dev/null || true
exec bash "${STARTUP_MAIN}"

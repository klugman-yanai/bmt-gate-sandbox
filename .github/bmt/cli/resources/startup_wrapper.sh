#!/usr/bin/env bash
# Startup wrapper loaded from VM metadata startup-script.
# Immutable runtime contract: execute baked startup script from local disk only.
set -euo pipefail

_read_meta() {
  local key="$1"
  curl -sSf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/${key}" 2>/dev/null || true
}

export GCS_BUCKET="${GCS_BUCKET:-$(_read_meta "GCS_BUCKET")}"
export BMT_REPO_ROOT="${BMT_REPO_ROOT:-$(_read_meta "BMT_REPO_ROOT")}"

GCS_BUCKET="${GCS_BUCKET:?Set metadata GCS_BUCKET}"
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
STARTUP_ENTRYPOINT="${BMT_REPO_ROOT}/bootstrap/startup_example.sh"

if [[ ! -f "${STARTUP_ENTRYPOINT}" ]]; then
  echo "::error::Missing baked startup entrypoint: ${STARTUP_ENTRYPOINT}" >&2
  echo "::error::Rebuild/provision VM from the hardened pre-baked runtime image." >&2
  exit 1
fi

chmod +x "${STARTUP_ENTRYPOINT}" 2>/dev/null || true
exec bash "${STARTUP_ENTRYPOINT}"

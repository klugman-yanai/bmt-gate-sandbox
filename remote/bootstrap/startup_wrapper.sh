#!/bin/bash
# Minimal wrapper for GCP "Startup script" metadata. Reads bucket config from
# instance custom metadata (set by setup_vm_startup.sh from GH variables) and
# runs the full startup script. The repo must already be at BMT_REPO_ROOT (e.g. /opt/bmt).
set -euo pipefail
_read() {
  curl -sSf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/${1}" 2>/dev/null || true
}
export GCS_BUCKET=$(_read "GCS_BUCKET")
export BMT_BUCKET_PREFIX=$(_read "BMT_BUCKET_PREFIX")
export BMT_REPO_ROOT=$(_read "BMT_REPO_ROOT")
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
exec "${BMT_REPO_ROOT}/remote/bootstrap/startup_example.sh"

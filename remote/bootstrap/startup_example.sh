#!/usr/bin/env bash
# Example startup script for the BMT watcher VM.
# 1. Install VM deps once (uv sync --extra vm from uv.lock; .venv under BMT_REPO_ROOT is persistent across stop/start).
# 2. Fetch GitHub App credentials from Secret Manager and export.
# 3. Start vm_watcher.py.
#
# Use as GCP "Startup script" (VM metadata) or from systemd. Set the variables
# below, or set them via VM custom metadata (see setup_vm_startup.sh), or export
# before running. Requires gcloud and the VM service account to have
# roles/secretmanager.secretAccessor on the three secrets.

set -euo pipefail

# --- Read from GCP instance metadata if not already set (matches GH variables) ---
_read_meta() {
  local key="$1"
  curl -sSf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/${key}" 2>/dev/null || true
}
if [[ -z "${GCS_BUCKET:-}" ]]; then
  GCS_BUCKET=$(_read_meta "GCS_BUCKET")
fi
if [[ -z "${BMT_BUCKET_PREFIX:-}" ]]; then
  BMT_BUCKET_PREFIX=$(_read_meta "BMT_BUCKET_PREFIX")
fi
if [[ -z "${BMT_REPO_ROOT:-}" ]]; then
  BMT_REPO_ROOT=$(_read_meta "BMT_REPO_ROOT")
fi

# --- Configure these (or already set via VM metadata / env above) ---
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET or VM metadata GCS_BUCKET}"
BMT_BUCKET_PREFIX="${BMT_BUCKET_PREFIX:-}"
BMT_WORKSPACE_ROOT="${BMT_WORKSPACE_ROOT:-$HOME/sk_runtime}"
# Secret Manager secret IDs (defaults match README)
GITHUB_APP_SECRET_ID_APP="${GITHUB_APP_SECRET_ID_APP:-GITHUB_APP_ID}"
GITHUB_APP_SECRET_ID_INSTALL="${GITHUB_APP_SECRET_ID_INSTALL:-GITHUB_APP_INSTALLATION_ID}"
GITHUB_APP_SECRET_ID_KEY="${GITHUB_APP_SECRET_ID_KEY:-GITHUB_APP_PRIVATE_KEY}"

VENV="${BMT_REPO_ROOT}/.venv"
WATCHER="${BMT_REPO_ROOT}/remote/vm_watcher.py"

# 1. Install deps once (requires uv on PATH and uv.lock in repo; install manually once via SSH if needed)
if [[ ! -d "$VENV" ]] || ! "${VENV}/bin/python" -c "import jwt" 2>/dev/null; then
  if [[ -f "${BMT_REPO_ROOT}/remote/bootstrap/install_deps.sh" ]]; then
    "${BMT_REPO_ROOT}/remote/bootstrap/install_deps.sh" "$BMT_REPO_ROOT"
  else
    command -v uv &>/dev/null || { echo "uv not found" >&2; exit 1; }
    cd "$BMT_REPO_ROOT" && uv sync --extra vm --frozen
  fi
fi

# 2. Fetch secrets and export
# Fetch test repo GitHub App credentials (non-blocking if not configured)
if gcloud secrets describe GITHUB_APP_TEST_ID &>/dev/null; then
  echo "Fetching GitHub App credentials for test environment..."
  GITHUB_APP_TEST_ID=$(gcloud secrets versions access latest --secret="GITHUB_APP_TEST_ID" 2>/dev/null || echo "")
  GITHUB_APP_TEST_INSTALLATION_ID=$(gcloud secrets versions access latest --secret="GITHUB_APP_TEST_INSTALLATION_ID" 2>/dev/null || echo "")
  GITHUB_APP_TEST_PRIVATE_KEY=$(gcloud secrets versions access latest --secret="GITHUB_APP_TEST_PRIVATE_KEY" 2>/dev/null || echo "")
  export GITHUB_APP_TEST_ID GITHUB_APP_TEST_INSTALLATION_ID GITHUB_APP_TEST_PRIVATE_KEY
  if [[ -n "$GITHUB_APP_TEST_ID" ]]; then
    echo "✓ Loaded GitHub App credentials for test environment"
  fi
fi

# Fetch prod repo GitHub App credentials (non-blocking if not configured)
if gcloud secrets describe GITHUB_APP_PROD_ID &>/dev/null; then
  echo "Fetching GitHub App credentials for prod environment..."
  GITHUB_APP_PROD_ID=$(gcloud secrets versions access latest --secret="GITHUB_APP_PROD_ID" 2>/dev/null || echo "")
  GITHUB_APP_PROD_INSTALLATION_ID=$(gcloud secrets versions access latest --secret="GITHUB_APP_PROD_INSTALLATION_ID" 2>/dev/null || echo "")
  GITHUB_APP_PROD_PRIVATE_KEY=$(gcloud secrets versions access latest --secret="GITHUB_APP_PROD_PRIVATE_KEY" 2>/dev/null || echo "")
  export GITHUB_APP_PROD_ID GITHUB_APP_PROD_INSTALLATION_ID GITHUB_APP_PROD_PRIVATE_KEY
  if [[ -n "$GITHUB_APP_PROD_ID" ]]; then
    echo "✓ Loaded GitHub App credentials for prod environment"
  fi
fi

# Preserve PAT fallback (if set)
if [[ -n "${GITHUB_STATUS_TOKEN:-}" ]]; then
  export GITHUB_STATUS_TOKEN
  echo "✓ PAT token available as fallback"
fi

# 3. Run watcher once with uv-managed Python and always attempt self-stop afterwards.
#    This prevents stale RUNNING VMs after failed runs/startup errors.
WATCHER_EXIT=0
if (cd "$BMT_REPO_ROOT" && uv run python remote/vm_watcher.py \
  --bucket "$GCS_BUCKET" \
  --bucket-prefix "$BMT_BUCKET_PREFIX" \
  --workspace-root "$BMT_WORKSPACE_ROOT" \
  --exit-after-run); then
  WATCHER_EXIT=0
else
  WATCHER_EXIT=$?
  echo "Watcher exited with non-zero status: ${WATCHER_EXIT}"
fi

INSTANCE=$(curl -sS -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/name" || true)
ZONE=$(curl -sS -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/zone" | sed 's|.*/||' || true)
PROJECT=$(curl -sS -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/project/project-id" || true)
if [[ -n "$INSTANCE" && -n "$ZONE" && -n "$PROJECT" ]]; then
  echo "Stopping VM $INSTANCE (zone=$ZONE project=$PROJECT)."
  gcloud compute instances stop "$INSTANCE" --zone "$ZONE" --project "$PROJECT" || true
else
  echo "Warning: Could not resolve instance metadata for self-stop." >&2
fi

exit "$WATCHER_EXIT"

#!/usr/bin/env bash
# Example startup script for the BMT watcher VM.
# 1. Install VM deps once (uv sync --extra vm from uv.lock; .venv under BMT_REPO_ROOT is persistent across stop/start).
# 2. Fetch GitHub App credentials from Secret Manager and export.
# 3. Start vm_watcher.py.
#
# Use as GCP "Startup script" (VM metadata) or from systemd. Set the variables
# below, or set them via VM custom metadata (see setup_vm_startup.sh), or export
# before running. Requires gcloud and the VM service account to have
# roles/secretmanager.secretAccessor on the configured GitHub App secrets.

set -euo pipefail

_self_stop_enabled="${BMT_SELF_STOP:-1}"

# shellcheck disable=SC2329
_stop_instance_best_effort() {
  local exit_code="$1"
  if [[ "${_self_stop_enabled}" != "1" ]]; then
    echo "Self-stop disabled (BMT_SELF_STOP=${_self_stop_enabled}); leaving VM running."
    return
  fi
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "Warning: gcloud not found; cannot self-stop VM (exit=${exit_code})." >&2
    return
  fi
  local instance zone project
  instance=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/name" || true)
  zone=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" | sed 's|.*/||' || true)
  project=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/project/project-id" || true)
  if [[ -n "$instance" && -n "$zone" && -n "$project" ]]; then
    echo "Stopping VM $instance (zone=$zone project=$project), script exit=${exit_code}."
    gcloud compute instances stop "$instance" --zone "$zone" --project "$project" || true
  else
    echo "Warning: Could not resolve instance metadata for self-stop (exit=${exit_code})." >&2
  fi
}

# shellcheck disable=SC2329
_on_exit() {
  local rc=$?
  trap - EXIT
  _stop_instance_best_effort "$rc"
  exit "$rc"
}

trap _on_exit EXIT

# --- Read from GCP instance metadata if not already set (matches GH variables) ---
_read_meta() {
  local key="$1"
  curl -sSf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/${key}" 2>/dev/null || true
}
if [[ -z "${GCS_BUCKET:-}" ]]; then
  GCS_BUCKET=$(_read_meta "GCS_BUCKET")
fi
if [[ -z "${BMT_REPO_ROOT:-}" ]]; then
  BMT_REPO_ROOT=$(_read_meta "BMT_REPO_ROOT")
fi
if [[ -z "${GCP_PROJECT:-}" ]]; then
  GCP_PROJECT=$(_read_meta "GCP_PROJECT")
fi

# --- Configure these (or already set via VM metadata / env above) ---
BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET or VM metadata GCS_BUCKET}"
if [[ -z "${GCP_PROJECT:-}" ]]; then
  GCP_PROJECT=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/project/project-id" 2>/dev/null || true)
fi
HOME_DIR="${HOME:-/root}"
if [[ -z "${BMT_WORKSPACE_ROOT:-}" ]]; then
  if [[ -d "${HOME_DIR}/sk_runtime" && ! -d "${HOME_DIR}/bmt_workspace" ]]; then
    echo "Warning: using legacy workspace path ${HOME_DIR}/sk_runtime"
    BMT_WORKSPACE_ROOT="${HOME_DIR}/sk_runtime"
  else
    BMT_WORKSPACE_ROOT="${HOME_DIR}/bmt_workspace"
  fi
fi

VENV="${BMT_REPO_ROOT}/.venv"
WATCHER="${BMT_REPO_ROOT}/vm_watcher.py"
ENSURE_UV="${BMT_REPO_ROOT}/bootstrap/ensure_uv.sh"

if [[ ! -f "${WATCHER}" ]]; then
  echo "::error::Missing watcher entrypoint: ${WATCHER}" >&2
  exit 1
fi

# 1. Resolve uv binary (override allowed via BMT_UV_BIN; otherwise bootstraps
#    pinned code artifact when uv is missing on the VM image).
if [[ ! -f "${ENSURE_UV}" ]]; then
  echo "::error::Missing UV bootstrap helper: ${ENSURE_UV}" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "${ENSURE_UV}"
if [[ -z "${UV_BIN:-}" || ! -x "${UV_BIN}" ]]; then
  echo "::error::UV resolution failed; UV_BIN is not executable (${UV_BIN:-<unset>})" >&2
  exit 1
fi

# 2. Install deps once (requires uv.lock in repo; install into persistent BMT_REPO_ROOT/.venv)
if [[ ! -d "$VENV" ]] || ! "${VENV}/bin/python" -c "import jwt" 2>/dev/null; then
  if [[ -f "${BMT_REPO_ROOT}/bootstrap/install_deps.sh" ]]; then
    bash "${BMT_REPO_ROOT}/bootstrap/install_deps.sh" "$BMT_REPO_ROOT"
  else
    cd "$BMT_REPO_ROOT" && "${UV_BIN}" sync --extra vm --frozen
  fi
fi

# 3. Fetch secrets and export.
# Canonical groups only:
#   - GITHUB_APP_TEST_*
#   - GITHUB_APP_PROD_*

# Regional secrets: configure gcloud to use the regional Secret Manager endpoint.
# Set BMT_SECRETS_LOCATION to override; defaults to the VM zone's region.
# When set, gcloud secrets commands route through the regional endpoint automatically.
if [[ -z "${BMT_SECRETS_LOCATION:-}" ]]; then
  _vm_zone=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" 2>/dev/null | sed 's|.*/||' || true)
  BMT_SECRETS_LOCATION="${_vm_zone%-*}"
fi

if [[ -n "${BMT_SECRETS_LOCATION:-}" ]]; then
  gcloud config set api_endpoint_overrides/secretmanager \
    "https://secretmanager.${BMT_SECRETS_LOCATION}.rep.googleapis.com/" 2>/dev/null
  echo "Configured regional Secret Manager endpoint for ${BMT_SECRETS_LOCATION}"
fi

_access_secret() {
  local secret_name="$1"
  gcloud secrets versions access latest \
    --secret="$secret_name" \
    --location="${BMT_SECRETS_LOCATION:-}" \
    --project="${GCP_PROJECT}" 2>/dev/null
}

_load_github_app_credentials() {
  local env_label="$1"
  local prefix="$2"
  local id_secret="${prefix}_ID"
  local installation_secret="${prefix}_INSTALLATION_ID"
  local key_secret="${prefix}_PRIVATE_KEY"

  local app_id installation_id private_key
  app_id=$(_access_secret "$id_secret" 2>/dev/null || true)
  if [[ -z "$app_id" ]]; then
    echo "Info: ${env_label}: GitHub App secrets not found/readable (${id_secret}) in project ${GCP_PROJECT:-<default>}."
    return 0
  fi

  installation_id=$(_access_secret "$installation_secret" 2>/dev/null || true)
  private_key=$(_access_secret "$key_secret" 2>/dev/null || true)
  if [[ -z "$installation_id" || -z "$private_key" ]]; then
    echo "Warning: ${env_label}: secret set ${prefix}_* partially available but values are missing/unreadable."
    return 0
  fi

  local id_var="${prefix}_ID"
  local installation_var="${prefix}_INSTALLATION_ID"
  local key_var="${prefix}_PRIVATE_KEY"
  printf -v "$id_var" "%s" "$app_id"
  printf -v "$installation_var" "%s" "$installation_id"
  printf -v "$key_var" "%s" "$private_key"
  export "${id_var?}" "${installation_var?}" "${key_var?}"

  echo "✓ Loaded GitHub App credentials for ${env_label} from ${prefix}_*"
  return 0
}

_load_github_app_credentials "test environment" "GITHUB_APP_TEST"
_load_github_app_credentials "prod environment" "GITHUB_APP_PROD"

# 4. Run watcher once with uv-managed Python and always attempt self-stop afterwards.
#    This prevents stale RUNNING VMs after failed runs/startup errors.
WATCHER_EXIT=0
if (cd "$BMT_REPO_ROOT" && "${UV_BIN}" run python vm_watcher.py \
  --bucket "$GCS_BUCKET" \
  --workspace-root "$BMT_WORKSPACE_ROOT" \
  --exit-after-run); then
  WATCHER_EXIT=0
else
  WATCHER_EXIT=$?
  echo "Watcher exited with non-zero status: ${WATCHER_EXIT}"
fi

exit "$WATCHER_EXIT"

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
  local instance zone project
  instance=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/name" || true)
  zone=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" | sed 's|.*/||' || true)
  project=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/project/project-id" || true)
  if [[ -n "$instance" && -n "$zone" && -n "$project" ]]; then
    echo "Stopping VM $instance (zone=$zone project=$project), script exit=${exit_code}."
    if command -v gcloud >/dev/null 2>&1; then
      if gcloud compute instances stop "$instance" --zone "$zone" --project "$project"; then
        echo "Self-stop succeeded via gcloud CLI."
        return
      fi
      echo "Warning: gcloud stop command failed; attempting Compute API fallback." >&2
    fi

    # Fallback path: call Compute Engine stop API directly with metadata token.
    # This avoids hard dependency on gcloud path/install during failure handling.
    local token_json access_token stop_url http_code
    token_json="$(curl -sS -H "Metadata-Flavor: Google" \
      "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" || true)"
    access_token="$(printf '%s' "$token_json" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("access_token") or "").strip())' 2>/dev/null || true)"
    if [[ -z "$access_token" ]]; then
      echo "Warning: unable to obtain metadata access token for API self-stop." >&2
      return
    fi
    stop_url="https://compute.googleapis.com/compute/v1/projects/${project}/zones/${zone}/instances/${instance}/stop"
    http_code="$(curl -sS -o /tmp/bmt-self-stop-response.json -w '%{http_code}' \
      -X POST \
      -H "Authorization: Bearer ${access_token}" \
      -H "Content-Type: application/json" \
      "$stop_url" || true)"
    if [[ "$http_code" =~ ^2[0-9][0-9]$ || "$http_code" == "409" ]]; then
      echo "Self-stop succeeded via Compute API fallback (HTTP ${http_code})."
      return
    fi
    echo "Warning: Compute API self-stop failed (HTTP ${http_code})." >&2
  else
    echo "Warning: Could not resolve instance metadata for self-stop (exit=${exit_code})." >&2
  fi
}

# shellcheck disable=SC2329
_on_exit() {
  local rc=$?
  trap - EXIT
  # Upload watcher log to GCS before stopping VM (best-effort; never blocks stop).
  if [[ -f "${BMT_LOG_FILE:-}" && -n "${GCS_BUCKET:-}" ]]; then
    local _log_vm_name
    _log_vm_name=$(curl -sS -H "Metadata-Flavor: Google" \
      "http://metadata.google.internal/computeMetadata/v1/instance/name" 2>/dev/null || echo "unknown")
    gcloud storage cp "$BMT_LOG_FILE" \
      "gs://${GCS_BUCKET}/runtime/logs/${_log_vm_name}-$(date +%Y%m%dT%H%M%S).log" \
      --quiet 2>/dev/null || echo "Warning: watcher log upload to GCS failed." >&2
  fi
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
DEP_STAMP="${VENV}/.bmt_dep_fingerprint"

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

# 2. Install deps when required (fingerprint or import mismatch).
_compute_dep_fingerprint() {
  local repo_root="$1"
  local pyproject="${repo_root}/pyproject.toml"
  local uvlock="${repo_root}/uv.lock"
  if [[ -f "$pyproject" && -f "$uvlock" ]]; then
    sha256sum "$pyproject" "$uvlock" | sha256sum | awk '{print $1}'
    return 0
  fi
  if [[ -f "$pyproject" ]]; then
    sha256sum "$pyproject" | awk '{print $1}'
    return 0
  fi
  return 1
}

dep_fingerprint="$(_compute_dep_fingerprint "$BMT_REPO_ROOT" || true)"
deps_reason=""
needs_deps_install=0

if [[ ! -d "$VENV" ]]; then
  needs_deps_install=1
  deps_reason="venv_missing"
elif [[ ! -x "${VENV}/bin/python" ]] || ! "${VENV}/bin/python" -c "import jwt" 2>/dev/null; then
  needs_deps_install=1
  deps_reason="runtime_import_check_failed"
elif [[ -z "$dep_fingerprint" ]]; then
  needs_deps_install=1
  deps_reason="fingerprint_unavailable"
elif [[ ! -f "$DEP_STAMP" ]]; then
  needs_deps_install=1
  deps_reason="fingerprint_stamp_missing"
else
  current_fingerprint="$(tr -d '[:space:]' <"$DEP_STAMP" || true)"
  if [[ "$current_fingerprint" != "$dep_fingerprint" ]]; then
    needs_deps_install=1
    deps_reason="fingerprint_mismatch"
  fi
fi

if [[ "$needs_deps_install" -eq 1 ]]; then
  echo "Dependency install required (${deps_reason})."
  if [[ -f "${BMT_REPO_ROOT}/bootstrap/install_deps.sh" ]]; then
    bash "${BMT_REPO_ROOT}/bootstrap/install_deps.sh" "$BMT_REPO_ROOT"
  else
    cd "$BMT_REPO_ROOT" && "${UV_BIN}" sync --extra vm --frozen
    if [[ -n "$dep_fingerprint" ]]; then
      mkdir -p "$(dirname "$DEP_STAMP")"
      printf '%s\n' "$dep_fingerprint" >"$DEP_STAMP"
    fi
  fi
else
  echo "Dependency fingerprint match (${dep_fingerprint}); skipping install."
fi

# 3. Fetch secrets and export.
# Canonical groups:
#   - GITHUB_APP_TEST_*
#   - GITHUB_APP_PROD_*
# Alias compatibility groups (fallback only):
#   - GH_APP_TEST_*
#   - GH_APP_PROD_*

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
  local -a location_flag=()
  if [[ -n "${BMT_SECRETS_LOCATION:-}" ]]; then
    location_flag=(--location="${BMT_SECRETS_LOCATION}")
  fi
  gcloud secrets versions access latest \
    --secret="$secret_name" \
    "${location_flag[@]}" \
    --project="${GCP_PROJECT}" 2>/dev/null
}

_access_secret_with_retry() {
  local secret_name="$1" attempt delay=2 out
  for attempt in 1 2 3; do
    out=$(_access_secret "$secret_name") && { printf '%s' "$out"; return 0; }
    [[ "$attempt" -lt 3 ]] && echo "  Secret access attempt ${attempt}/3 failed for ${secret_name}; retrying in ${delay}s." >&2 && sleep "$delay" && delay=$((delay * 2))
  done
  return 1
}

_load_github_app_credentials() {
  local env_label="$1"
  local prefix="$2"
  local alias_prefix=""
  local -a candidate_prefixes=()
  local selected_prefix=""

  if [[ "$prefix" == GITHUB_APP_* ]]; then
    alias_prefix="GH_APP_${prefix#GITHUB_APP_}"
  fi

  candidate_prefixes=("$prefix")
  if [[ -n "$alias_prefix" && "$alias_prefix" != "$prefix" ]]; then
    candidate_prefixes+=("$alias_prefix")
  fi

  local app_id installation_id private_key
  app_id=""
  installation_id=""
  private_key=""

  local candidate
  for candidate in "${candidate_prefixes[@]}"; do
    app_id=$(_access_secret_with_retry "${candidate}_ID" 2>/dev/null || true)
    if [[ -n "$app_id" ]]; then
      selected_prefix="$candidate"
      break
    fi
  done
  if [[ -z "$app_id" ]]; then
    echo "Info: ${env_label}: GitHub App secrets not found/readable (${prefix}_ID) in project ${GCP_PROJECT:-<default>}."
    return 0
  fi

  for candidate in "${candidate_prefixes[@]}"; do
    installation_id=$(_access_secret_with_retry "${candidate}_INSTALLATION_ID" 2>/dev/null || true)
    if [[ -n "$installation_id" ]]; then
      [[ -z "$selected_prefix" ]] && selected_prefix="$candidate"
      break
    fi
  done
  for candidate in "${candidate_prefixes[@]}"; do
    private_key=$(_access_secret_with_retry "${candidate}_PRIVATE_KEY" 2>/dev/null || true)
    if [[ -n "$private_key" ]]; then
      [[ -z "$selected_prefix" ]] && selected_prefix="$candidate"
      break
    fi
  done
  if [[ -z "$installation_id" || -z "$private_key" ]]; then
    echo "Warning: ${env_label}: secret set ${prefix}_* partially available but values are missing/unreadable."
    return 0
  fi

  if [[ -n "$selected_prefix" && "$selected_prefix" != "$prefix" ]]; then
    echo "Warning: ${env_label}: using alias secret prefix ${selected_prefix}_*; prefer canonical ${prefix}_*."
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
#    Tee all output to a log file; _on_exit uploads it to GCS for post-mortem debugging.
BMT_LOG_FILE="/tmp/bmt-watcher-$(date +%Y%m%dT%H%M%S).log"
echo "Watcher log: ${BMT_LOG_FILE} (will be uploaded to gs://${GCS_BUCKET}/runtime/logs/ on exit)"

WATCHER_EXIT=0
(
  cd "$BMT_REPO_ROOT"
  "${UV_BIN}" run python vm_watcher.py \
    --bucket "$GCS_BUCKET" \
    --workspace-root "$BMT_WORKSPACE_ROOT" \
    --exit-after-run 2>&1 | tee "$BMT_LOG_FILE"
  exit "${PIPESTATUS[0]}"
) || WATCHER_EXIT=$?
if [[ "$WATCHER_EXIT" -ne 0 ]]; then
  echo "Watcher exited with non-zero status: ${WATCHER_EXIT}"
fi

exit "$WATCHER_EXIT"

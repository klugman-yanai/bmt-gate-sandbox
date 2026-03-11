#!/usr/bin/env bash
# Run the BMT watcher on the VM: validate pre-baked runtime, load GitHub App secrets, run vm_watcher.py, then self-stop.
# Invoked by startup_entrypoint.sh (GCP startup-script) or systemd. Set variables via VM custom metadata or export.
# Requires gcloud and VM service account with roles/secretmanager.secretAccessor for GitHub App secrets.
#
# Debug: set BMT_DEBUG=1 (e.g. in VM metadata) to enable bash -x style tracing.

set -euo pipefail
[[ "${BMT_DEBUG:-0}" == "1" ]] && set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/shared.sh"
_bmt_log_tag="run_watcher"

_self_stop_enabled="${BMT_SELF_STOP:-1}"
BMT_LOG_FILE="/tmp/bmt-startup-$(date +%Y%m%dT%H%M%S).log"
touch "$BMT_LOG_FILE"
exec > >(tee -a "$BMT_LOG_FILE") 2>&1

_log "Phase: startup; log file=${BMT_LOG_FILE}"
# shellcheck disable=SC2329
_stop_instance_best_effort() {
  local exit_code="$1"
  if [[ "${_self_stop_enabled}" != "1" ]]; then
    _log "Self-stop disabled (BMT_SELF_STOP=${_self_stop_enabled}); leaving VM running."
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
    _log "Stopping VM instance=${instance} zone=${zone} project=${project} exit_code=${exit_code}"
    if command -v gcloud >/dev/null 2>&1; then
      if gcloud compute instances stop "$instance" --zone "$zone" --project "$project"; then
        _log "Self-stop succeeded via gcloud CLI."
        return
      fi
      _log_err "Warning: gcloud stop command failed; attempting Compute API fallback."
    fi

    local token_json access_token stop_url http_code
    token_json="$(curl -sS -H "Metadata-Flavor: Google" \
      "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" || true)"
    access_token="$(printf '%s' "$token_json" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("access_token") or "").strip())' 2>/dev/null || true)"
    if [[ -z "$access_token" ]]; then
      _log_err "Warning: unable to obtain metadata access token for API self-stop."
      return
    fi
    stop_url="https://compute.googleapis.com/compute/v1/projects/${project}/zones/${zone}/instances/${instance}/stop"
    http_code="$(curl -sS -o /tmp/bmt-self-stop-response.json -w '%{http_code}' \
      -X POST \
      -H "Authorization: Bearer ${access_token}" \
      -H "Content-Type: application/json" \
      "$stop_url" || true)"
    if [[ "$http_code" =~ ^2[0-9][0-9]$ || "$http_code" == "409" ]]; then
      _log "Self-stop succeeded via Compute API fallback (HTTP ${http_code})."
      return
    fi
    _log_err "Warning: Compute API self-stop failed (HTTP ${http_code})."
  else
    _log_err "Warning: Could not resolve instance metadata for self-stop (exit=${exit_code})."
  fi
}

_on_exit() {
  local rc=$?
  trap - EXIT
  _log "Phase: exit handler; exit_code=${rc}"
  if [[ -f "${BMT_LOG_FILE:-}" && -n "${GCS_BUCKET:-}" ]]; then
    local _log_vm_name
    _log_vm_name=$(curl -sS -H "Metadata-Flavor: Google" \
      "http://metadata.google.internal/computeMetadata/v1/instance/name" 2>/dev/null || echo "unknown")
    if gcloud storage cp "$BMT_LOG_FILE" \
      "gs://${GCS_BUCKET}/runtime/logs/${_log_vm_name}-$(date +%Y%m%dT%H%M%S).log" \
      --quiet 2>/dev/null; then
      _log "Uploaded startup log to GCS."
    else
      _log_err "Warning: watcher log upload to GCS failed."
    fi
  fi
  _stop_instance_best_effort "$rc"
  exit "$rc"
}

trap _on_exit EXIT

_log "Phase: reading VM metadata"
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
if [[ -z "${BMT_PUBSUB_SUBSCRIPTION:-}" ]]; then
  BMT_PUBSUB_SUBSCRIPTION=$(_read_meta "BMT_PUBSUB_SUBSCRIPTION")
fi

BMT_REPO_ROOT="${BMT_REPO_ROOT:-/opt/bmt}"
GCS_BUCKET="${GCS_BUCKET:?Set GCS_BUCKET or VM metadata GCS_BUCKET}"
if [[ -z "${GCP_PROJECT:-}" ]]; then
  GCP_PROJECT=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/project/project-id" 2>/dev/null || true)
fi
_log "Config: BMT_REPO_ROOT=${BMT_REPO_ROOT} GCS_BUCKET=${GCS_BUCKET} GCP_PROJECT=${GCP_PROJECT:-<unset>}"

HOME_DIR="${HOME:-/root}"
if [[ -z "${BMT_WORKSPACE_ROOT:-}" ]]; then
  if [[ -d "${HOME_DIR}/sk_runtime" && ! -d "${HOME_DIR}/bmt_workspace" ]]; then
    _log_err "Warning: using legacy workspace path ${HOME_DIR}/sk_runtime"
    BMT_WORKSPACE_ROOT="${HOME_DIR}/sk_runtime"
  else
    BMT_WORKSPACE_ROOT="${HOME_DIR}/bmt_workspace"
  fi
fi
_log "Workspace root: ${BMT_WORKSPACE_ROOT}"

VENV="${BMT_REPO_ROOT}/.venv"
WATCHER="${BMT_REPO_ROOT}/vm_watcher.py"

_log "Phase: validating pre-baked runtime"
if [[ ! -f "${WATCHER}" ]]; then
  _log_err "::error::Missing watcher entrypoint: ${WATCHER}"
  exit 1
fi

PYTHON_BIN="${VENV}/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  _log_err "::error::Missing pre-baked python at ${PYTHON_BIN}"
  _log_err "::error::Runtime dependency install is disabled at startup; rebuild/provision image."
  exit 1
fi

if ! "${PYTHON_BIN}" - <<'PY'
import importlib.util
import sys

required = [
    "jwt",
    "cryptography",
    "httpx",
    "google.cloud.storage",
]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if (
    importlib.util.find_spec("google.cloud.pubsub_v1") is None
    and importlib.util.find_spec("google.cloud.pubsub") is None
):
    missing.append("google.cloud.pubsub_v1|google.cloud.pubsub")

if missing:
    print("Missing required pre-baked modules:", ", ".join(missing), file=sys.stderr)
    sys.exit(1)
PY
then
  _log_err "::error::Pre-baked runtime import validation failed."
  _log_err "::error::Runtime dependency install is disabled at startup; rebuild/provision image."
  exit 1
fi
_log "Pre-baked runtime validation passed."

_log "Phase: loading GitHub App credentials from Secret Manager"
if [[ -z "${BMT_SECRETS_LOCATION:-}" ]]; then
  _vm_zone=$(curl -sS -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" 2>/dev/null | sed 's|.*/||' || true)
  BMT_SECRETS_LOCATION="${_vm_zone%-*}"
fi

if [[ -n "${BMT_SECRETS_LOCATION:-}" ]]; then
  gcloud config set api_endpoint_overrides/secretmanager \
    "https://secretmanager.${BMT_SECRETS_LOCATION}.rep.googleapis.com/" 2>/dev/null
  _log "Configured regional Secret Manager endpoint: ${BMT_SECRETS_LOCATION}"
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
    [[ "$attempt" -lt 3 ]] && _log_err "Secret access attempt ${attempt}/3 failed for ${secret_name}; retrying in ${delay}s." && sleep "$delay" && delay=$((delay * 2))
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
    _log "Info: ${env_label}: GitHub App secrets not found/readable (${prefix}_ID) in project ${GCP_PROJECT:-<default>}."
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
    _log_err "Warning: ${env_label}: secret set ${prefix}_* partially available but values are missing/unreadable."
    return 0
  fi

  if [[ -n "$selected_prefix" && "$selected_prefix" != "$prefix" ]]; then
    _log_err "Warning: ${env_label}: using alias secret prefix ${selected_prefix}_*; prefer canonical ${prefix}_*."
  fi

  local id_var="${prefix}_ID"
  local installation_var="${prefix}_INSTALLATION_ID"
  local key_var="${prefix}_PRIVATE_KEY"
  printf -v "$id_var" "%s" "$app_id"
  printf -v "$installation_var" "%s" "$installation_id"
  printf -v "$key_var" "%s" "$private_key"
  export "${id_var?}" "${installation_var?}" "${key_var?}"

  _log "Loaded GitHub App credentials for ${env_label} from ${prefix}_*"
  return 0
}

_load_github_app_credentials "test environment" "GITHUB_APP_TEST"
_load_github_app_credentials "prod environment" "GITHUB_APP_PROD"

_log "Phase: launching vm_watcher.py"

WATCHER_EXIT=0
_watcher_extra_args=()
if [[ -n "${BMT_PUBSUB_SUBSCRIPTION:-}" && -n "${GCP_PROJECT:-}" ]]; then
  _watcher_extra_args+=(--subscription "projects/${GCP_PROJECT}/subscriptions/${BMT_PUBSUB_SUBSCRIPTION}")
  _watcher_extra_args+=(--gcp-project "${GCP_PROJECT}")
  _log "Pub/Sub subscription: projects/${GCP_PROJECT}/subscriptions/${BMT_PUBSUB_SUBSCRIPTION}"
fi
_idle_sec="${BMT_IDLE_TIMEOUT_SEC:-600}"
_watcher_extra_args+=(--idle-timeout-sec "${_idle_sec}")
(
  cd "$BMT_REPO_ROOT"
  "${PYTHON_BIN}" vm_watcher.py \
    --bucket "$GCS_BUCKET" \
    --workspace-root "$BMT_WORKSPACE_ROOT" \
    --exit-after-run \
    "${_watcher_extra_args[@]}"
) || WATCHER_EXIT=$?
if [[ "$WATCHER_EXIT" -ne 0 ]]; then
  _log_err "Watcher exited with non-zero status: ${WATCHER_EXIT}"
fi

_log "Phase: done; exiting with ${WATCHER_EXIT}"
exit "$WATCHER_EXIT"

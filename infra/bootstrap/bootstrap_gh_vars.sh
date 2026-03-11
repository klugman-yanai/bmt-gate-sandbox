#!/usr/bin/env bash
# bootstrap_gh_vars.sh — Apply BMT GitHub repo variables + secrets from an env file.
#
# Usage:
#   bash infra/bootstrap/bootstrap_gh_vars.sh [--env-file <path>] [--repo <owner/repo>]
#
# Prefer: run `just terraform-export-vars` first to set Terraform-sourced vars, then use
# this script with an env file containing only secrets (GCP_WIF_PROVIDER, BMT_DISPATCH_APP_*).
# Or pass a full env file to set/override all vars and secrets.
#
# Prerequisites:
# - gh CLI authenticated with repo write permissions
# - For file-based secrets, the referenced file must exist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
TARGET_REPO=""

usage() {
  cat <<'USAGE'
Usage:
  bash infra/bootstrap/bootstrap_gh_vars.sh [--env-file <path>] [--repo <owner/repo>]

Options:
  --env-file <path>   Path to env file (default: infra/bootstrap/.env)
  --repo <owner/repo> Target repository (default: current gh repo context)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      [[ $# -ge 2 ]] || {
        echo "error: --env-file requires a value" >&2
        exit 1
      }
      ENV_FILE="$2"
      shift 2
      ;;
    --repo)
      [[ $# -ge 2 ]] || {
        echo "error: --repo requires a value" >&2
        exit 1
      }
      TARGET_REPO="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh CLI is required but not found in PATH" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: $ENV_FILE" >&2
  exit 1
fi

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

strip_outer_quotes() {
  local s="$1"
  if [[ "${#s}" -ge 2 ]]; then
    if [[ "${s:0:1}" == '"' && "${s: -1}" == '"' ]]; then
      s="${s:1:${#s}-2}"
    elif [[ "${s:0:1}" == "'" && "${s: -1}" == "'" ]]; then
      s="${s:1:${#s}-2}"
    fi
  fi
  printf '%s' "$s"
}

contains_key() {
  local needle="$1"
  shift
  local item=""
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

resolve_secret_file() {
  local raw="$1"
  local env_dir=""
  local repo_root=""

  [[ -n "$raw" ]] || return 1

  if [[ -f "$raw" ]]; then
    printf '%s\n' "$raw"
    return 0
  fi

  env_dir="$(cd "$(dirname "$ENV_FILE")" && pwd)"
  if [[ -f "$env_dir/$raw" ]]; then
    printf '%s\n' "$env_dir/$raw"
    return 0
  fi

  repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "$repo_root" && -f "$repo_root/$raw" ]]; then
    printf '%s\n' "$repo_root/$raw"
    return 0
  fi

  return 1
}

GH_SCOPE_ARGS=()
if [[ -n "$TARGET_REPO" ]]; then
  GH_SCOPE_ARGS=(-R "$TARGET_REPO")
fi

BOOTSTRAP_RETRIES="${BOOTSTRAP_RETRIES:-5}"
BOOTSTRAP_RETRY_BASE_DELAY_SEC="${BOOTSTRAP_RETRY_BASE_DELAY_SEC:-1}"

is_transient_gh_error() {
  local msg="$1"
  [[ "$msg" == *"HTTP 5"* ]] || [[ "$msg" == *"Bad Gateway"* ]] || [[ "$msg" == *"timed out"* ]] || [[ "$msg" == *"timeout"* ]] || [[ "$msg" == *"connection reset"* ]] || [[ "$msg" == *"temporary failure"* ]]
}

run_gh_with_retry() {
  local op_desc="$1"
  shift
  local attempt=1
  local delay="$BOOTSTRAP_RETRY_BASE_DELAY_SEC"
  local out=""
  local rc=0
  while (( attempt <= BOOTSTRAP_RETRIES )); do
    if out="$("$@" 2>&1)"; then
      [[ -n "$out" ]] && echo "$out"
      return 0
    fi
    rc=$?
    if (( attempt < BOOTSTRAP_RETRIES )) && is_transient_gh_error "$out"; then
      echo "warning: ${op_desc} failed (attempt ${attempt}/${BOOTSTRAP_RETRIES}): $out" >&2
      sleep "$delay"
      delay=$(( delay * 2 ))
      attempt=$(( attempt + 1 ))
      continue
    fi
    echo "error: ${op_desc} failed: $out" >&2
    return "$rc"
  done
  return 1
}

run_gh_secret_from_file_with_retry() {
  local op_desc="$1"
  local secret_name="$2"
  local secret_file="$3"
  local attempt=1
  local delay="$BOOTSTRAP_RETRY_BASE_DELAY_SEC"
  local out=""
  local rc=0
  while (( attempt <= BOOTSTRAP_RETRIES )); do
    if out="$(gh secret set "$secret_name" "${GH_SCOPE_ARGS[@]}" < "$secret_file" 2>&1)"; then
      [[ -n "$out" ]] && echo "$out"
      return 0
    fi
    rc=$?
    if (( attempt < BOOTSTRAP_RETRIES )) && is_transient_gh_error "$out"; then
      echo "warning: ${op_desc} failed (attempt ${attempt}/${BOOTSTRAP_RETRIES}): $out" >&2
      sleep "$delay"
      delay=$(( delay * 2 ))
      attempt=$(( attempt + 1 ))
      continue
    fi
    echo "error: ${op_desc} failed: $out" >&2
    return "$rc"
  done
  return 1
}

validate_wif_provider() {
  local provider="$1"
  local project_id="$2"
  if [[ ! "$provider" =~ ^projects/([0-9]+)/locations/global/workloadIdentityPools/([^/]+)/providers/([^/]+)$ ]]; then
    echo "error: GCP_WIF_PROVIDER invalid format: $provider" >&2
    return 1
  fi
  local provider_project_number="${BASH_REMATCH[1]}"
  if command -v gcloud >/dev/null 2>&1; then
    local actual_project_number=""
    actual_project_number="$(gcloud projects describe "$project_id" --format='value(projectNumber)' 2>/dev/null || true)"
    if [[ -n "$actual_project_number" && "$provider_project_number" != "$actual_project_number" ]]; then
      echo "error: GCP_WIF_PROVIDER project number mismatch" >&2
      return 1
    fi
  fi
  return 0
}

REQUIRED_VARS=(
  GCS_BUCKET
  GCP_WIF_PROVIDER
  GCP_SA_EMAIL
  GCP_PROJECT
  GCP_ZONE
  BMT_VM_NAME
  BMT_PUBSUB_SUBSCRIPTION
)

OPTIONAL_VARS=(
  BMT_PROJECTS
  BMT_STATUS_CONTEXT
  BMT_RUNTIME_CONTEXT
  BMT_HANDSHAKE_TIMEOUT_SEC
  BMT_PREEMPT_ON_PR_STALE_QUEUE
  BMT_TRIGGER_STALE_SEC
  BMT_TRIGGER_METADATA_KEEP_RECENT
  BMT_DISPATCH_APP_ID
)

SECRET_KEYS=(
  BMT_DISPATCH_APP_PRIVATE_KEY
)

declare -A ENTRIES
while IFS='=' read -r key rest || [[ -n "${key}${rest}" ]]; do
  key="$(trim "${key:-}")"
  [[ -z "$key" || "$key" == \#* ]] && continue
  value="${rest%%#*}"
  value="$(trim "$value")"
  value="$(strip_outer_quotes "$value")"
  [[ -n "$value" ]] && ENTRIES["$key"]="$value"
done < "$ENV_FILE"

missing=()
for name in "${REQUIRED_VARS[@]}"; do
  [[ -z "${ENTRIES[$name]:-}" ]] && missing+=("$name")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "error: required keys missing in $ENV_FILE:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 1
fi

if ! validate_wif_provider "${ENTRIES[GCP_WIF_PROVIDER]}" "${ENTRIES[GCP_PROJECT]}"; then
  exit 1
fi

for key in "${!ENTRIES[@]}"; do
  if contains_key "$key" "${REQUIRED_VARS[@]}" || contains_key "$key" "${OPTIONAL_VARS[@]}" || contains_key "$key" "${SECRET_KEYS[@]}"; then
    continue
  fi
  echo "warning: ignoring unknown key '$key' in $ENV_FILE" >&2
done

failures=()
echo "Applying GitHub repository variables from $ENV_FILE ..."
for name in "${REQUIRED_VARS[@]}" "${OPTIONAL_VARS[@]}"; do
  value="${ENTRIES[$name]:-}"
  [[ -n "$value" ]] || continue
  if run_gh_with_retry "set variable $name" gh variable set "$name" "${GH_SCOPE_ARGS[@]}" --body "$value"; then
    echo "  set variable $name"
  else
    failures+=("variable:$name")
  fi
done

echo "Applying GitHub repository secrets from $ENV_FILE ..."
for name in "${SECRET_KEYS[@]}"; do
  value="${ENTRIES[$name]:-}"
  [[ -n "$value" ]] || continue
  if secret_file="$(resolve_secret_file "$value")"; then
    if run_gh_secret_from_file_with_retry "set secret $name from file $secret_file" "$name" "$secret_file"; then
      echo "  set secret $name from file $secret_file"
    else
      failures+=("secret:$name")
    fi
  else
    if run_gh_with_retry "set secret $name (inline)" gh secret set "$name" "${GH_SCOPE_ARGS[@]}" --body "$value"; then
      echo "  set secret $name"
    else
      failures+=("secret:$name")
    fi
  fi
done

if [[ ${#failures[@]} -gt 0 ]]; then
  echo "" >&2
  echo "error: bootstrap finished with failures:" >&2
  printf '  %s\n' "${failures[@]}" >&2
  exit 1
fi

echo ""
echo "Done. Verify: gh variable list ${GH_SCOPE_ARGS[*]}  gh secret list ${GH_SCOPE_ARGS[*]}"

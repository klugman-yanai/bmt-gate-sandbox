#!/usr/bin/env bash
# bootstrap_gh_vars.sh — Set required GitHub repository variables for bmt.yml.
#
# Usage:
#   bash .github/bmt/config/bootstrap_gh_vars.sh [--env-file <path>]
#
# Reads KEY=VALUE lines from the env file (default: .env in this config dir),
# skips comments and blank lines, skips empty values, and calls:
#   gh variable set KEY --body VALUE
# for each non-empty entry.
#
# Prerequisites: gh CLI authenticated with repo write permissions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--env-file <path>]" >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: $ENV_FILE" >&2
  echo "Copy .env.example to .env in this directory and fill in your values, then re-run." >&2
  exit 1
fi

REQUIRED=(
  # Required for client/CI: GCP auth, bucket, and VM targeting. Optional vars
  # (BMT_PROJECTS, BMT_STATUS_CONTEXT, BMT_HANDSHAKE_TIMEOUT_SEC) are not listed.
  GCS_BUCKET
  GCP_WIF_PROVIDER
  GCP_SA_EMAIL
  GCP_PROJECT
  GCP_ZONE
  BMT_VM_NAME
)

declare -A VARS
while IFS='=' read -r key rest; do
  [[ -z "$key" || "$key" == \#* ]] && continue
  # Strip inline comments and surrounding whitespace from the value
  value="${rest%%#*}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  [[ -n "$key" && -n "$value" ]] && VARS["$key"]="$value"
done < "$ENV_FILE"

# Validate required vars are all set
missing=()
for name in "${REQUIRED[@]}"; do
  [[ -z "${VARS[$name]:-}" ]] && missing+=("$name")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "error: the following required variables are not set in $ENV_FILE:" >&2
  for name in "${missing[@]}"; do
    echo "  $name" >&2
  done
  exit 1
fi

echo "Setting GitHub repository variables from $ENV_FILE ..."
for name in "${!VARS[@]}"; do
  value="${VARS[$name]}"
  gh variable set "$name" --body "$value"
  echo "  set $name"
done

echo ""
echo "Done. Verify with: gh variable list"

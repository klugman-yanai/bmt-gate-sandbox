#!/usr/bin/env bash

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "::error::Required command not found: $1"
    exit 1
  fi
}

normalize_prefix() {
  local raw="${1:-}"
  raw="${raw#/}"
  raw="${raw%/}"
  printf '%s' "$raw"
}

runtime_prefix() {
  local parent
  parent="$(normalize_prefix "${BMT_BUCKET_PREFIX:-}")"
  if [[ -n "$parent" ]]; then
    printf '%s/runtime' "$parent"
  else
    printf 'runtime'
  fi
}

runtime_root() {
  if [[ -z "${GCS_BUCKET:-}" ]]; then
    echo "::error::GCS_BUCKET is required"
    exit 1
  fi
  printf 'gs://%s/%s' "$GCS_BUCKET" "$(runtime_prefix)"
}

current_run_id() {
  local run_id="${WORKFLOW_RUN_ID:-}"
  if [[ -z "$run_id" ]]; then
    run_id="${GITHUB_RUN_ID:-}"
  fi
  if [[ -z "$run_id" ]]; then
    echo "::error::WORKFLOW_RUN_ID or GITHUB_RUN_ID is required"
    exit 1
  fi
  printf '%s' "$run_id"
}

#!/usr/bin/env bash

bmt_cmd_emit_bmt_context() {
  if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
    echo "::error::GITHUB_OUTPUT is not set"
    exit 1
  fi
  {
    echo "run_id=${DISPATCH_CI_RUN_ID:-}"
    echo "head_sha=${DISPATCH_HEAD_SHA:-}"
    echo "head_branch=${DISPATCH_HEAD_BRANCH:-}"
    echo "head_event=${DISPATCH_HEAD_EVENT:-}"
    echo "pr_number=${DISPATCH_PR_NUMBER:-}"
  } >>"$GITHUB_OUTPUT"
}

bmt_cmd_validate_required_vars() {
  local required missing name value
  required=(GCS_BUCKET GCP_WIF_PROVIDER GCP_SA_EMAIL GCP_PROJECT GCP_ZONE BMT_VM_NAME)
  missing=()
  for name in "${required[@]}"; do
    value="${!name:-}"
    if [[ -z "$value" ]]; then
      missing+=("$name")
    fi
  done

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "::error::Missing required repo vars: ${missing[*]}"
    exit 1
  fi
  echo "Proceeding with BMT"
}

# Fail-fast if legacy BMT_BUCKET_PREFIX repo var is set (non-empty).
# Used by the workflow with vars.BMT_BUCKET_PREFIX; unset or empty is OK.
bmt_cmd_guard_no_legacy_prefix() {
  local prefix="${BMT_BUCKET_PREFIX:-}"
  if [[ -n "${prefix// /}" ]]; then
    echo "::error::Legacy BMT_BUCKET_PREFIX='${prefix}' is set in repository variables. BMT_BUCKET_PREFIX has been removed; clear it in Settings → Secrets and variables → Actions → Variables."
    exit 1
  fi
}

bmt_cmd_resolve_failure_context() {
  local mode head_sha pr_number vm_handshake_result trigger_written

  if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
    echo "::error::GITHUB_OUTPUT is not set"
    exit 1
  fi

  mode="context"
  if [[ "${PREPARE_RESULT:-}" == "failure" ]]; then
    mode="no_context"
  fi

  head_sha="${PREPARE_HEAD_SHA:-}"
  if [[ -z "$head_sha" ]]; then
    head_sha="${DISPATCH_HEAD_SHA:-${GITHUB_SHA:-}}"
  fi

  pr_number="${PREPARE_PR_NUMBER:-}"
  if [[ -z "$pr_number" ]]; then
    pr_number="${DISPATCH_PR_NUMBER:-}"
  fi

  vm_handshake_result="success"
  if [[ "${ORCH_HAS_LEGS:-}" == "true" && "${ORCH_HANDSHAKE_OK:-}" != "true" ]]; then
    vm_handshake_result="failure"
  fi

  trigger_written="false"
  if [[ "${ORCH_TRIGGER_WRITTEN:-}" == "true" ]]; then
    trigger_written="true"
  fi

  {
    echo "mode=${mode}"
    echo "head_sha=${head_sha}"
    echo "pr_number=${pr_number}"
    echo "vm_handshake_result=${vm_handshake_result}"
    echo "trigger_written=${trigger_written}"
  } >>"$GITHUB_OUTPUT"
}

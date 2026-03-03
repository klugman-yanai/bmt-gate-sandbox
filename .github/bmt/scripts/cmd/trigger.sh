#!/usr/bin/env bash

bmt_cmd_preflight_trigger_queue() {
  local run_id root runs_prefix current_uri run_context
  local preempt_on_pr_raw preempt_on_pr stale_sec
  local -a existing blocking
  local uri removed failed rid count prefix_uri

  require_cmd gcloud
  run_id="$(current_run_id)"
  run_context="${RUN_CONTEXT:-dev}"
  preempt_on_pr_raw="${BMT_PREEMPT_ON_PR_STALE_QUEUE:-1}"
  stale_sec="${BMT_TRIGGER_STALE_SEC:-900}"
  root="$(runtime_root)"
  runs_prefix="${root}/triggers/runs/"
  current_uri="${runs_prefix}${run_id}.json"

  if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
    echo "::error::GITHUB_OUTPUT is not set"
    exit 1
  fi

  echo "restart_vm=false" >>"$GITHUB_OUTPUT"
  echo "stale_cleanup_count=0" >>"$GITHUB_OUTPUT"

  case "${preempt_on_pr_raw,,}" in
    1|true|yes|on) preempt_on_pr="true" ;;
    *) preempt_on_pr="false" ;;
  esac

  mapfile -t existing < <(gcloud storage ls "$runs_prefix" 2>/dev/null | sed '/\/$/d' | grep '\.json$' || true)
  blocking=()
  for uri in "${existing[@]}"; do
    [[ "$uri" == "$current_uri" ]] && continue
    blocking+=("$uri")
  done

  {
    echo "## Runtime Trigger Preflight"
    echo
    echo "- Run context: \`${run_context}\`"
    echo "- Preempt PR stale queue: \`${preempt_on_pr}\`"
    echo "- Stale trigger threshold (seconds): \`${stale_sec}\`"
    echo "- Runtime root: \`${root}\`"
    echo "- Existing trigger files: **${#existing[@]}**"
    echo "- Blocking stale trigger files: **${#blocking[@]}**"
  } >>"$GITHUB_STEP_SUMMARY"

  if [[ "${#blocking[@]}" -eq 0 ]]; then
    echo "- Action: no stale trigger cleanup required." >>"$GITHUB_STEP_SUMMARY"
    exit 0
  fi

  if [[ "$run_context" == "pr" && "$preempt_on_pr" != "true" ]]; then
    {
      echo "- Action: observational only (BMT_PREEMPT_ON_PR_STALE_QUEUE disabled); no trigger deletion, no forced VM restart."
      echo
      echo "### Existing queue entries"
      echo
      echo "| Trigger URI |"
      echo "|------------|"
    } >>"$GITHUB_STEP_SUMMARY"
    for uri in "${blocking[@]}"; do
      echo "| \`${uri}\` |" >>"$GITHUB_STEP_SUMMARY"
    done
    exit 0
  fi

  {
    echo
    echo "### Stale triggers found (to remove)"
    echo
    echo "| Trigger URI |"
    echo "|------------|"
  } >>"$GITHUB_STEP_SUMMARY"

  for uri in "${blocking[@]}"; do
    echo "| \`${uri}\` |" >>"$GITHUB_STEP_SUMMARY"
  done

  removed=0
  failed=0
  for uri in "${blocking[@]}"; do
    if gcloud storage rm "$uri" >/dev/null 2>&1; then
      removed=$((removed + 1))
      rid="$(basename "$uri")"
      rid="${rid%.json}"
      gcloud storage rm "${root}/triggers/acks/${rid}.json" >/dev/null 2>&1 || true
      gcloud storage rm "${root}/triggers/status/${rid}.json" >/dev/null 2>&1 || true
    else
      failed=$((failed + 1))
    fi
  done

  echo "stale_cleanup_count=${removed}" >>"$GITHUB_OUTPUT"
  if [[ "$removed" -gt 0 ]]; then
    echo "restart_vm=true" >>"$GITHUB_OUTPUT"
  fi

  {
    echo
    echo "### Preflight cleanup result"
    echo
    echo "- Removed stale run triggers: **${removed}**"
    echo "- Failed removals: **${failed}**"
    if [[ "$removed" -gt 0 ]]; then
      echo "- Requested VM clean restart before handshake: **yes**"
    else
      echo "- Requested VM clean restart before handshake: **no**"
    fi
  } >>"$GITHUB_STEP_SUMMARY"

  if [[ "$failed" -gt 0 ]]; then
    echo "::error::Failed to remove ${failed} stale trigger file(s) under ${runs_prefix}."
    exit 1
  fi

  for prefix_uri in \
    "${root}/triggers/runs/" \
    "${root}/triggers/acks/" \
    "${root}/triggers/status/"; do
    count="$(gcloud storage ls "$prefix_uri" 2>/dev/null | wc -l | tr -d ' ')"
    count="${count:-0}"
    echo "- ${prefix_uri} count after cleanup: ${count}" >>"$GITHUB_STEP_SUMMARY"
  done
}

bmt_cmd_write_run_trigger() {
  require_cmd uv
  if [[ -z "${FILTERED_MATRIX_JSON:-}" ]]; then
    echo "::error::FILTERED_MATRIX_JSON is required"
    exit 1
  fi
  uv run bmt trigger
}

bmt_cmd_force_clean_vm_restart() {
  local stale_count status_before status_now terminated

  require_cmd gcloud
  stale_count="${STALE_CLEANUP_COUNT:-0}"

  echo "Stale trigger cleanup removed ${stale_count} file(s); forcing clean VM restart."

  status_before="$(gcloud compute instances describe "$BMT_VM_NAME" --zone "$GCP_ZONE" --project "$GCP_PROJECT" --format='value(status)' 2>/dev/null || echo UNKNOWN)"
  echo "VM status before restart action: ${status_before}"

  if [[ "$status_before" != "TERMINATED" ]]; then
    gcloud compute instances stop "$BMT_VM_NAME" --zone "$GCP_ZONE" --project "$GCP_PROJECT" >/dev/null 2>&1 || true
  fi

  terminated=0
  for _ in $(seq 1 24); do
    status_now="$(gcloud compute instances describe "$BMT_VM_NAME" --zone "$GCP_ZONE" --project "$GCP_PROJECT" --format='value(status)' 2>/dev/null || echo UNKNOWN)"
    if [[ "$status_now" == "TERMINATED" ]]; then
      terminated=1
      break
    fi
    sleep 5
  done

  if [[ "$terminated" -ne 1 ]]; then
    echo "::error::VM did not reach TERMINATED before restart sequence."
    exit 1
  fi
  echo "VM reached TERMINATED; proceeding with normal start step."
}

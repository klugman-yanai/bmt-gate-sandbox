#!/usr/bin/env bash

bmt__trigger_payload_is_valid() {
  local uri payload
  uri="$1"
  payload="$(gcloud storage cat "$uri" 2>/dev/null || true)"
  if [[ -z "$payload" ]]; then
    return 1
  fi
  echo "$payload" | jq -e '
    type == "object" and
    ((.workflow_run_id | type) == "string" or (.workflow_run_id | type) == "number") and
    ((.repository | type) == "string" and (.repository | test(".+/.+"))) and
    ((.sha | type) == "string" and (.sha | test("^[0-9a-fA-F]{40}$"))) and
    ((.ref | type) == "string" and (.ref | startswith("refs/"))) and
    ((.bucket | type) == "string" and (.bucket | length > 0)) and
    ((.legs | type) == "array" and (.legs | length > 0)) and
    all(
      .legs[];
      type == "object" and
      ((.project | type) == "string" and (.project | length > 0)) and
      ((.bmt_id | type) == "string" and (.bmt_id | length > 0)) and
      ((.run_id | type) == "string" and (.run_id | length > 0))
    )
  ' >/dev/null 2>&1
}

bmt__trim_trigger_family_keep_recent() {
  local family_prefix keep_recent
  local -a uris run_ids keep_ids
  local uri rid keep_list removed

  family_prefix="$1"
  keep_recent="$2"

  mapfile -t uris < <(gcloud storage ls "$family_prefix" 2>/dev/null | sed '/\/$/d' | grep '\.json$' || true)
  if [[ "${#uris[@]}" -eq 0 ]]; then
    echo 0
    return 0
  fi

  run_ids=()
  for uri in "${uris[@]}"; do
    rid="$(basename "$uri")"
    rid="${rid%.json}"
    [[ -z "$rid" ]] && continue
    run_ids+=("$rid")
  done
  if [[ "${#run_ids[@]}" -eq 0 ]]; then
    echo 0
    return 0
  fi

  # Keep newest workflow IDs (numeric IDs sort naturally with -V).
  mapfile -t keep_ids < <(printf '%s\n' "${run_ids[@]}" | awk '!seen[$0]++' | sort -rV | head -n "$keep_recent")
  keep_list="$(printf ',%s,' "${keep_ids[@]}")"

  removed=0
  for uri in "${uris[@]}"; do
    rid="$(basename "$uri")"
    rid="${rid%.json}"
    if [[ "$keep_list" == *",$rid,"* ]]; then
      continue
    fi
    if gcloud storage rm "$uri" >/dev/null 2>&1; then
      removed=$((removed + 1))
    fi
  done

  echo "$removed"
  return 0
}

bmt_cmd_preflight_trigger_queue() {
  local run_id root runs_prefix current_uri run_context
  local preempt_on_pr_raw preempt_on_pr stale_sec keep_recent
  local -a existing blocking invalid
  local uri removed failed invalid_removed invalid_failed rid count prefix_uri trimmed
  local trim_runs trim_acks trim_status

  require_cmd gcloud
  require_cmd jq
  run_id="$(current_run_id)"
  run_context="${RUN_CONTEXT:-dev}"
  preempt_on_pr_raw="${BMT_PREEMPT_ON_PR_STALE_QUEUE:-1}"
  stale_sec="${BMT_TRIGGER_STALE_SEC:-900}"
  keep_recent="${BMT_TRIGGER_METADATA_KEEP_RECENT:-2}"
  if ! [[ "$keep_recent" =~ ^[0-9]+$ ]]; then
    keep_recent=2
  fi
  if [[ "$keep_recent" -lt 1 ]]; then
    keep_recent=1
  fi
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
  invalid=()
  blocking=()
  for uri in "${existing[@]}"; do
    [[ "$uri" == "$current_uri" ]] && continue
    if bmt__trigger_payload_is_valid "$uri"; then
      blocking+=("$uri")
    else
      invalid+=("$uri")
    fi
  done

  {
    echo "## Runtime Trigger Preflight"
    echo
    echo "- Run context: \`${run_context}\`"
    echo "- Preempt PR stale queue: \`${preempt_on_pr}\`"
    echo "- Stale trigger threshold (seconds): \`${stale_sec}\`"
    echo "- Trigger metadata keep recent: \`${keep_recent}\`"
    echo "- Runtime root: \`${root}\`"
    echo "- Existing trigger files: **${#existing[@]}**"
    echo "- Invalid trigger files: **${#invalid[@]}**"
    echo "- Blocking trigger files: **${#blocking[@]}**"
  } >>"$GITHUB_STEP_SUMMARY"

  invalid_removed=0
  invalid_failed=0
  for uri in "${invalid[@]}"; do
    if gcloud storage rm "$uri" >/dev/null 2>&1; then
      invalid_removed=$((invalid_removed + 1))
      rid="$(basename "$uri")"
      rid="${rid%.json}"
      gcloud storage rm "${root}/triggers/acks/${rid}.json" >/dev/null 2>&1 || true
      gcloud storage rm "${root}/triggers/status/${rid}.json" >/dev/null 2>&1 || true
    else
      invalid_failed=$((invalid_failed + 1))
    fi
  done

  if [[ "$invalid_removed" -gt 0 || "$invalid_failed" -gt 0 ]]; then
    {
      echo
      echo "### Invalid trigger cleanup"
      echo
      echo "- Removed invalid run triggers: **${invalid_removed}**"
      echo "- Failed invalid-trigger removals: **${invalid_failed}**"
    } >>"$GITHUB_STEP_SUMMARY"
  fi
  if [[ "$invalid_failed" -gt 0 ]]; then
    echo "::error::Failed to remove ${invalid_failed} invalid trigger file(s) under ${runs_prefix}."
    exit 1
  fi

  if [[ "${#blocking[@]}" -eq 0 ]]; then
    echo "- Action: no blocking trigger cleanup required." >>"$GITHUB_STEP_SUMMARY"
  elif [[ "$run_context" == "pr" && "$preempt_on_pr" != "true" ]]; then
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
  else
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
  fi

  trim_runs="$(bmt__trim_trigger_family_keep_recent "${root}/triggers/runs/" "$keep_recent")"
  trim_acks="$(bmt__trim_trigger_family_keep_recent "${root}/triggers/acks/" "$keep_recent")"
  trim_status="$(bmt__trim_trigger_family_keep_recent "${root}/triggers/status/" "$keep_recent")"
  trimmed=$((trim_runs + trim_acks + trim_status))
  {
    echo
    echo "### Metadata retention trim"
    echo
    echo "- Trimmed trigger-run JSONs: **${trim_runs}**"
    echo "- Trimmed handshake-ack JSONs: **${trim_acks}**"
    echo "- Trimmed runtime-status JSONs: **${trim_status}**"
    echo "- Total metadata objects trimmed: **${trimmed}**"
  } >>"$GITHUB_STEP_SUMMARY"

  for prefix_uri in \
    "${root}/triggers/runs/" \
    "${root}/triggers/acks/" \
    "${root}/triggers/status/"; do
    # gcloud returns non-zero when a prefix has no objects; treat that as count=0.
    count="$(gcloud storage ls "$prefix_uri" 2>/dev/null | wc -l | tr -d ' ' || true)"
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
  uv run --project .github/bmt bmt trigger
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

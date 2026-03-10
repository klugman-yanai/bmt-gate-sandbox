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

bmt__gcs_err_is_not_found() {
  local text="${1:-}"
  text="${text,,}"
  [[ "$text" == *"no urls matched"* ]] && return 0
  [[ "$text" == *"matched no objects"* ]] && return 0
  [[ "$text" == *"notfound"* ]] && return 0
  [[ "$text" == *"404"* ]] && return 0
  return 1
}

bmt__gcs_err_is_transient() {
  local text="${1:-}"
  text="${text,,}"
  [[ "$text" == *"429"* ]] && return 0
  [[ "$text" == *"rate limit"* ]] && return 0
  [[ "$text" == *"quota"* ]] && return 0
  [[ "$text" == *"timeout"* ]] && return 0
  [[ "$text" == *"temporar"* ]] && return 0
  [[ "$text" == *"connection reset"* ]] && return 0
  [[ "$text" == *"broken pipe"* ]] && return 0
  [[ "$text" == *"internal error"* ]] && return 0
  [[ "$text" == *"503"* ]] && return 0
  [[ "$text" == *"500"* ]] && return 0
  return 1
}

# Delete a single GCS object idempotently.
# Prints one of: "removed" | "missing"
# Returns non-zero only on genuine errors (permission/retention/etc).
bmt__gcs_rm_idempotent() {
  local uri severity attempts attempt out rc
  uri="$1"
  severity="${2:-error}"   # error | warning | notice
  attempts="${3:-3}"

  if [[ -z "$uri" ]]; then
    echo "::${severity}::gcs_rm_idempotent called with empty uri"
    return 1
  fi

  for attempt in $(seq 1 "$attempts"); do
    out="$(gcloud storage rm "$uri" 2>&1)"
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
      echo "removed"
      return 0
    fi

    if bmt__gcs_err_is_not_found "$out"; then
      echo "missing"
      return 0
    fi

    if [[ "$attempt" -lt "$attempts" ]] && bmt__gcs_err_is_transient "$out"; then
      sleep "$attempt"
      continue
    fi

    echo "::${severity}::gcloud storage rm failed for ${uri}: ${out:-unknown error}"
    return 1
  done

  echo "::${severity}::gcloud storage rm failed for ${uri}: unknown error"
  return 1
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

bmt__trigger_age_sec() {
  local uri payload triggered_at now_epoch triggered_epoch
  uri="$1"
  now_epoch="$2"

  payload="$(gcloud storage cat "$uri" 2>/dev/null || true)"
  if [[ -z "$payload" ]]; then
    echo ""
    return 0
  fi
  triggered_at="$(echo "$payload" | jq -r '.triggered_at // empty' 2>/dev/null || true)"
  if [[ -z "$triggered_at" ]]; then
    echo ""
    return 0
  fi
  triggered_epoch="$(date -u -d "$triggered_at" +%s 2>/dev/null || true)"
  if [[ -z "$triggered_epoch" ]]; then
    echo ""
    return 0
  fi
  if (( now_epoch < triggered_epoch )); then
    echo 0
    return 0
  fi
  echo $((now_epoch - triggered_epoch))
  return 0
}

bmt_cmd_preflight_trigger_queue() {
  local run_id root runs_prefix current_uri run_context
  local preempt_on_pr_raw preempt_on_pr stale_sec keep_recent
  local -a existing blocking invalid stale_blocking
  local uri removed missing failed invalid_removed invalid_missing invalid_failed rid count prefix_uri trimmed outcome age_sec
  local preserved_blocking now_epoch
  local trim_runs trim_acks trim_status

  require_cmd gcloud
  require_cmd jq
  run_id="$(current_run_id)"
  run_context="${RUN_CONTEXT:-dev}"
  preempt_on_pr_raw="${BMT_PREEMPT_ON_PR_STALE_QUEUE:-1}"
  stale_sec="${BMT_TRIGGER_STALE_SEC:-900}"
  if ! [[ "$stale_sec" =~ ^[0-9]+$ ]]; then
    stale_sec=900
  fi
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

  echo "::notice::Preflight: existing=${#existing[@]} invalid=${#invalid[@]} blocking=${#blocking[@]} context=${run_context}"

  invalid_removed=0
  invalid_missing=0
  invalid_failed=0
  for uri in "${invalid[@]}"; do
    outcome="$(bmt__gcs_rm_idempotent "$uri" error)" || { invalid_failed=$((invalid_failed + 1)); continue; }
    if [[ "$outcome" == "removed" ]]; then
      invalid_removed=$((invalid_removed + 1))
    else
      invalid_missing=$((invalid_missing + 1))
    fi
    rid="$(basename "$uri")"
    rid="${rid%.json}"
    bmt__gcs_rm_idempotent "${root}/triggers/acks/${rid}.json" warning 2 >/dev/null || true
    bmt__gcs_rm_idempotent "${root}/triggers/status/${rid}.json" warning 2 >/dev/null || true
  done

  if [[ "$invalid_removed" -gt 0 || "$invalid_missing" -gt 0 || "$invalid_failed" -gt 0 ]]; then
    echo "::notice::Invalid trigger cleanup: removed=${invalid_removed} missing=${invalid_missing} failed=${invalid_failed}"
  fi
  if [[ "$invalid_failed" -gt 0 ]]; then
    echo "::error::Failed to remove ${invalid_failed} invalid trigger file(s) under ${runs_prefix}. Ensure the workflow service account has storage.objects.delete on the bucket."
    exit 1
  fi

  if [[ "${#blocking[@]}" -eq 0 ]]; then
    echo "::notice::No blocking trigger cleanup required."
  elif [[ "$run_context" == "pr" && "$preempt_on_pr" != "true" ]]; then
    echo "::notice::Observational only (BMT_PREEMPT_ON_PR_STALE_QUEUE disabled); ${#blocking[@]} blocking trigger(s)."
    exit 0
  else
    stale_blocking=()
    preserved_blocking=0
    now_epoch="$(date -u +%s)"
    for uri in "${blocking[@]}"; do
      age_sec="$(bmt__trigger_age_sec "$uri" "$now_epoch")"
      if [[ -n "$age_sec" ]] && (( age_sec >= stale_sec )); then
        stale_blocking+=("$uri")
      else
        preserved_blocking=$((preserved_blocking + 1))
      fi
    done

    if [[ "${#stale_blocking[@]}" -gt 0 ]]; then
      echo "::notice::Removing ${#stale_blocking[@]} stale trigger(s) (threshold=${stale_sec}s)."
    fi
    if [[ "$preserved_blocking" -gt 0 ]]; then
      echo "::notice::Preserved ${preserved_blocking} active/unknown-age trigger(s); will not delete in-flight non-PR queue entries."
    fi

    removed=0
    missing=0
    failed=0
    for uri in "${stale_blocking[@]}"; do
      outcome="$(bmt__gcs_rm_idempotent "$uri" error)" || { failed=$((failed + 1)); continue; }
      if [[ "$outcome" == "removed" ]]; then
        removed=$((removed + 1))
      else
        missing=$((missing + 1))
      fi
      rid="$(basename "$uri")"
      rid="${rid%.json}"
      bmt__gcs_rm_idempotent "${root}/triggers/acks/${rid}.json" warning 2 >/dev/null || true
      bmt__gcs_rm_idempotent "${root}/triggers/status/${rid}.json" warning 2 >/dev/null || true
    done

    echo "stale_cleanup_count=${removed}" >>"$GITHUB_OUTPUT"
    if [[ "$removed" -gt 0 ]]; then
      echo "restart_vm=true" >>"$GITHUB_OUTPUT"
    fi

    echo "::notice::Preflight cleanup: removed=${removed} missing=${missing} failed=${failed} preserved=${preserved_blocking} restart_vm=$( [[ "$removed" -gt 0 ]] && echo yes || echo no )"

    if [[ "$failed" -gt 0 ]]; then
      echo "::error::Failed to remove ${failed} stale trigger file(s) under ${runs_prefix}. Ensure the workflow service account has storage.objects.delete on the bucket."
      exit 1
    fi
  fi

  trim_runs="$(bmt__trim_trigger_family_keep_recent "${root}/triggers/runs/" "$keep_recent")"
  trim_acks="$(bmt__trim_trigger_family_keep_recent "${root}/triggers/acks/" "$keep_recent")"
  trim_status="$(bmt__trim_trigger_family_keep_recent "${root}/triggers/status/" "$keep_recent")"
  trimmed=$((trim_runs + trim_acks + trim_status))
  if [[ "$trimmed" -gt 0 ]]; then
    echo "::notice::Metadata trim: runs=${trim_runs} acks=${trim_acks} status=${trim_status} total=${trimmed}"
  fi
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

#!/usr/bin/env bash

bmt_cmd_show_handshake_guidance() {
  local run_id base_timeout timeout restart_vm stale_count root ack_uri trigger_uri

  run_id="$(current_run_id)"
  base_timeout="${BMT_HANDSHAKE_TIMEOUT_SEC:-180}"
  timeout="$base_timeout"
  restart_vm="${RESTART_VM:-false}"
  stale_count="${STALE_CLEANUP_COUNT:-0}"

  if [[ "$restart_vm" == "true" ]]; then
    timeout=$((base_timeout + 60))
  fi

  root="$(runtime_root)"
  ack_uri="${root}/triggers/acks/${run_id}.json"
  trigger_uri="${root}/triggers/runs/${run_id}.json"

  {
    echo "## VM handshake timeout: ${timeout}s (set repo var BMT_HANDSHAKE_TIMEOUT_SEC to override)"
    echo
    if [[ "$restart_vm" == "true" ]]; then
      echo "- Handshake mode: **post-cleanup restart branch** (stale trigger cleanup count: \`${stale_count}\`)"
      echo "- Timeout policy: base \`${base_timeout}\` + 60s warmup after forced restart."
    else
      echo "- Handshake mode: **standard branch** (no stale trigger cleanup)."
    fi
    echo
    echo "### Check VM / GCS while waiting"
    echo "- **Trigger file** (VM reads this): \`${trigger_uri}\`"
    echo "- **Ack file** (VM writes this when ready): \`${ack_uri}\`"
    echo "- Handshake confirms VM pickup only; final \`${BMT_STATUS_CONTEXT:-BMT Gate}\` status is posted after VM completion."
    echo "- **GCS:** \`gcloud storage cat \"${ack_uri}\"\` (after VM writes ack)"
    echo "- **VM serial output:** \`gcloud compute instances get-serial-port-output ${BMT_VM_NAME} --zone=${GCP_ZONE}\`"
    echo "- **Local TUI monitor:** \`just monitor --run-id ${run_id}\` or \`uv run python devtools/bmt_monitor.py --run-id ${run_id} --bucket ${GCS_BUCKET}\`"
  } >>"$GITHUB_STEP_SUMMARY"
}

bmt_cmd_wait_handshake() {
  local run_id base_timeout timeout restart_vm stale_count

  require_cmd uv
  run_id="$(current_run_id)"
  base_timeout="${BMT_HANDSHAKE_TIMEOUT_SEC:-180}"
  timeout="$base_timeout"
  restart_vm="${RESTART_VM:-false}"
  stale_count="${STALE_CLEANUP_COUNT:-0}"

  if [[ "$restart_vm" == "true" ]]; then
    timeout=$((base_timeout + 60))
    echo "::notice::Handshake branch=post-cleanup-restart stale_cleanup_count=${stale_count} timeout=${timeout}s"
  else
    echo "::notice::Handshake branch=standard timeout=${timeout}s"
  fi

  BMT_HANDSHAKE_TIMEOUT_SEC="$timeout" \
  uv run bmt wait-handshake
}

bmt_cmd_handshake_timeout_diagnostics() {
  local run_id root trigger_uri ack_uri

  require_cmd gcloud
  run_id="$(current_run_id)"
  root="$(runtime_root)"
  trigger_uri="${root}/triggers/runs/${run_id}.json"
  ack_uri="${root}/triggers/acks/${run_id}.json"

  set +e
  echo "::group::GCS trigger/ack diagnostics"
  echo "Trigger URI: ${trigger_uri}"
  echo "Ack URI: ${ack_uri}"
  gcloud storage ls "$trigger_uri" 2>/dev/null || true
  gcloud storage ls "$ack_uri" 2>/dev/null || true
  echo "--- trigger payload (first 120 lines) ---"
  gcloud storage cat "$trigger_uri" 2>/dev/null | sed -n '1,120p' || true
  echo "--- ack payload (first 120 lines) ---"
  gcloud storage cat "$ack_uri" 2>/dev/null | sed -n '1,120p' || true
  echo "::endgroup::"

  echo "::group::VM instance diagnostics"
  gcloud compute instances describe "$BMT_VM_NAME" \
    --zone "$GCP_ZONE" \
    --project "$GCP_PROJECT" \
    --format='yaml(name,status,lastStartTimestamp,lastStopTimestamp,metadata.items)' 2>/dev/null || true
  echo "::endgroup::"

  echo "::group::VM serial output tail"
  gcloud compute instances get-serial-port-output "$BMT_VM_NAME" \
    --zone "$GCP_ZONE" \
    --project "$GCP_PROJECT" 2>/dev/null | tail -n 200 || true
  echo "::endgroup::"
}

bmt_cmd_show_handshake_summary() {
  local ack_payload handshake_uri requested_count accepted_count restart_vm stale_count

  require_cmd jq
  ack_payload="${ACK_PAYLOAD:-}"
  handshake_uri="${HANDSHAKE_URI:-}"
  requested_count="${HANDSHAKE_REQUESTED_LEG_COUNT:-0}"
  accepted_count="${HANDSHAKE_ACCEPTED_LEG_COUNT:-0}"
  restart_vm="${RESTART_VM:-false}"
  stale_count="${STALE_CLEANUP_COUNT:-0}"

  if [[ -z "$ack_payload" ]]; then
    echo "::error::ACK_PAYLOAD is required"
    exit 1
  fi

  {
    echo "## VM Handshake Response"
    echo
    if [[ "$restart_vm" == "true" ]]; then
      echo "- Handshake branch: **post-cleanup-restart**"
    else
      echo "- Handshake branch: **standard**"
    fi
    echo "- Stale cleanup count: **${stale_count}**"
    echo "- Ack URI: \`${handshake_uri}\`"
    echo "- Requested legs: **${requested_count}**"
    echo "- Accepted legs: **${accepted_count}**"
    echo
    echo "| Project | BMT ID | Run ID |"
    echo "|---------|--------|--------|"
  } >>"$GITHUB_STEP_SUMMARY"

  echo "$ack_payload" | jq -r '.accepted_legs[] | "| \(.project) | \(.bmt_id) | \(.run_id) |"' >>"$GITHUB_STEP_SUMMARY"

  if echo "$ack_payload" | jq -e '.rejected_legs | length > 0' >/dev/null; then
    {
      echo
      echo "### Rejected Legs"
      echo
      echo "| Index | Reason |"
      echo "|-------|--------|"
    } >>"$GITHUB_STEP_SUMMARY"
    echo "$ack_payload" | jq -r '.rejected_legs[] | "| \(.index) | \(.reason) |"' >>"$GITHUB_STEP_SUMMARY"
  fi
}

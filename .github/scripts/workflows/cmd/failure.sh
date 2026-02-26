#!/usr/bin/env bash

bmt_cmd_cleanup_failed_trigger_artifacts() {
  local run_id root run_uri ack_uri status_uri prefix_uri count

  require_cmd gcloud
  run_id="$(current_run_id)"
  root="$(runtime_root)"

  set +e
  run_uri="${root}/triggers/runs/${run_id}.json"
  ack_uri="${root}/triggers/acks/${run_id}.json"
  status_uri="${root}/triggers/status/${run_id}.json"

  for uri in "$run_uri" "$ack_uri" "$status_uri"; do
    gcloud storage rm "$uri" >/dev/null 2>&1 || true
  done

  echo "::group::Trigger family counts after cleanup"
  for prefix_uri in \
    "${root}/triggers/runs/" \
    "${root}/triggers/acks/" \
    "${root}/triggers/status/"; do
    count="$(gcloud storage ls "$prefix_uri" 2>/dev/null | wc -l | tr -d ' ')"
    echo "${prefix_uri} ${count:-0}"
  done
  echo "::endgroup::"
}

bmt_cmd_stop_vm_best_effort() {
  require_cmd gcloud
  set +e
  gcloud compute instances stop "$BMT_VM_NAME" \
    --zone "$GCP_ZONE" \
    --project "$GCP_PROJECT" >/dev/null 2>&1 || true
}

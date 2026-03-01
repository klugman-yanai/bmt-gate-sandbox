#!/usr/bin/env bash

bmt_cmd_post_handoff_timeout_status() {
  local repository head_sha github_token context

  repository="${REPOSITORY:-${GITHUB_REPOSITORY:-}}"
  head_sha="${HEAD_SHA:-}"
  github_token="${GITHUB_TOKEN:-}"
  context="${BMT_STATUS_CONTEXT:-BMT Gate}"

  if [[ -z "$repository" || -z "$head_sha" || -z "$github_token" ]]; then
    echo "::warning::Skipping fallback status post (missing repository/head_sha/token)."
    return 0
  fi

  if ! gh_should_post_failure_status "$repository" "$head_sha" "$github_token" "$context"; then
    echo "::notice::Fallback status skipped: '${context}' is already terminal for ${head_sha}."
    return 0
  fi

  if gh_post_status \
    "$repository" \
    "$head_sha" \
    "$github_token" \
    "error" \
    "$context" \
    "BMT cancelled: VM handshake timeout before pickup."; then
    echo "::notice::Posted fallback terminal status '${context}=error' for ${head_sha}."
  else
    echo "::warning::Failed to post fallback terminal status for ${head_sha}."
  fi
}

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

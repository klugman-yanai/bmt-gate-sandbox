#!/usr/bin/env bash

bmt_cmd_warn_artifact_missing() {
  local project preset
  project="${PROJECT:-unknown-project}"
  preset="${PRESET:-unknown-preset}"
  echo "::warning::Runner upload skipped for ${project} (${preset}): artifact not found or download failed. BMT will continue with other runners."
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "upload_ok=false" >>"$GITHUB_OUTPUT"
  fi
}

bmt_cmd_upload_runner_to_gcs() {
  require_cmd uv
  if [[ -z "${PROJECT:-}" || -z "${PRESET:-}" || -z "${SOURCE_REF:-}" ]]; then
    echo "::error::PROJECT, PRESET, and SOURCE_REF are required"
    exit 1
  fi
  chmod +x "artifact/Runners/kardome_runner" 2>/dev/null || true
  uv run --project .github/bmt bmt upload-runner
}

bmt_cmd_warn_upload_failed() {
  local project preset
  project="${PROJECT:-unknown-project}"
  preset="${PRESET:-unknown-preset}"
  echo "::warning::Runner upload failed for ${project} (${preset}). BMT will continue with other runners."
}

bmt_cmd_record_uploaded_project_marker() {
  local project run_id root

  require_cmd gcloud
  project="${PROJECT:-}"
  run_id="$(current_run_id)"

  if [[ -z "$project" ]]; then
    echo "::error::PROJECT is required"
    exit 1
  fi

  root="$(runtime_root)"
  echo '{}' | gcloud storage cp - "${root}/_workflow/uploaded/${run_id}/${project}.json"
}

bmt_cmd_resolve_uploaded_projects() {
  local run_id root prefix

  require_cmd gcloud
  require_cmd jq
  run_id="$(current_run_id)"
  root="$(runtime_root)"
  prefix="${root}/_workflow/uploaded/${run_id}/"

  if gcloud storage ls "$prefix" 2>/dev/null | grep '\.json$' > /dev/null; then
    gcloud storage ls "$prefix" 2>/dev/null \
      | sed 's|.*/||;s|\.json$||' \
      | jq -Rsc 'split("\n") | map(select(length>0)) | sort' > accepted.txt
  else
    echo '[]' > accepted.txt
  fi

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "accepted_projects=$(cat accepted.txt)" >>"$GITHUB_OUTPUT"
  fi
  echo "::notice::Runners uploaded for projects: $(cat accepted.txt)"
}

bmt_cmd_summarize_matrix_handshake() {
  local runner_matrix accepted filtered_matrix requested bmt_legs proj up leg status

  require_cmd jq
  runner_matrix="${RUNNER_MATRIX:-}"
  accepted="${ACCEPTED:-[]}"
  filtered_matrix="${FILTERED_MATRIX:-}"

  if [[ -z "$runner_matrix" || -z "$filtered_matrix" ]]; then
    echo "::error::RUNNER_MATRIX and FILTERED_MATRIX are required"
    exit 1
  fi

  echo "$runner_matrix" > /tmp/runner_matrix.json
  echo "$filtered_matrix" > /tmp/filtered_matrix.json

  local uploaded_count bmt_leg_count
  uploaded_count="$(echo "$accepted" | jq 'length')"
  bmt_leg_count="$(jq -c '[.include[].project] | unique | length' /tmp/filtered_matrix.json)"

  echo "::notice::Matrix handshake: uploaded=${uploaded_count} legs=${bmt_leg_count}"
}

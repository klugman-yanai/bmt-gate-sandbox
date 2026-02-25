#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: .github/scripts/workflows/bmt_workflow.sh <command>

Commands:
  emit-bmt-context
  validate-required-vars
  parse-release-runner-matrix
  warn-artifact-missing
  upload-runner-to-gcs
  warn-upload-failed
  record-uploaded-project-marker
  resolve-uploaded-projects
  filter-supported-matrix
  summarize-matrix-handshake
  preflight-trigger-queue
  write-run-trigger
  force-clean-vm-restart
  show-handshake-guidance
  wait-handshake
  wait-verdicts
  handshake-timeout-diagnostics
  show-handshake-summary
  post-pending-status
  post-final-status-from-decision
  post-started-pending
  post-skipped-success-status
  post-failure-status
  post-failure-pr-comment
  cleanup-failed-trigger-artifacts
  stop-vm-best-effort
  post-no-context-failure-status
  post-no-context-pr-comment
USAGE
}

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

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi
shift || true

case "$cmd" in
  emit-bmt-context)
    if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
      echo "::error::GITHUB_OUTPUT is not set"
      exit 1
    fi
    echo "run_id=${DISPATCH_CI_RUN_ID:-}" >>"$GITHUB_OUTPUT"
    echo "head_sha=${DISPATCH_HEAD_SHA:-}" >>"$GITHUB_OUTPUT"
    echo "head_branch=${DISPATCH_HEAD_BRANCH:-}" >>"$GITHUB_OUTPUT"
    echo "head_event=${DISPATCH_HEAD_EVENT:-}" >>"$GITHUB_OUTPUT"
    echo "pr_number=${DISPATCH_PR_NUMBER:-}" >>"$GITHUB_OUTPUT"
    ;;

  validate-required-vars)
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
    ;;

  parse-release-runner-matrix)
    require_cmd jq
    allowed_raw="${BMT_PROJECTS:-all release runners}"
    allowed_norm="$(echo "$allowed_raw" | tr '[:upper:]' '[:lower:]' | xargs)"
    if [[ -z "$allowed_norm" || "$allowed_norm" == "all" || "$allowed_norm" == "*" || "$allowed_norm" == "all release runners" || "$allowed_norm" == "all-release-runners" || "$allowed_norm" == "all_release_runners" ]]; then
      allowed_json='null'
    else
      allowed_json="$(echo "$allowed_raw" | jq -Rc 'split(",") | map(gsub("^ +| +$"; "") | ascii_downcase) | map(select(length>0))')"
    fi

    runner_matrix="$(jq -c --argjson allowed "$allowed_json" '
      { include:
        [ .configurePresets[]
          | select(.name | test("_gcc_Release$"))
          | select(.name | test("xtensa|hexagon") | not)
          | (.name | sub("_gcc_Release$"; "") | ascii_downcase) as $proj
          | select($allowed == null or ($allowed | index($proj)))
          | { configure: .name,
              preset: (.name | ascii_downcase),
              project: $proj,
              binary_dir: (.binaryDir | sub("\\$\\{sourceDir\\}/"; "")) }
        ] }' CMakePresets.json)"

    if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
      echo "::error::GITHUB_OUTPUT is not set"
      exit 1
    fi

    echo "runner_matrix=$runner_matrix" >>"$GITHUB_OUTPUT"
    echo "::notice::Runner matrix (BMT_PROJECTS=${allowed_raw}): $runner_matrix"
    ;;

  warn-artifact-missing)
    project="${PROJECT:-unknown-project}"
    preset="${PRESET:-unknown-preset}"
    echo "::warning::Runner upload skipped for ${project} (${preset}): artifact not found or download failed. BMT will continue with other runners."
    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
      echo "upload_ok=false" >>"$GITHUB_OUTPUT"
    fi
    ;;

  upload-runner-to-gcs)
    require_cmd uv
    project="${PROJECT:-}"
    preset="${PRESET:-}"
    source_ref="${SOURCE_REF:-}"
    if [[ -z "$project" || -z "$preset" || -z "$source_ref" ]]; then
      echo "::error::PROJECT, PRESET, and SOURCE_REF are required"
      exit 1
    fi

    runner_dir="artifact/Runners"
    lib_dir="artifact/Kardome"

    lib_arg=()
    if [[ -d "$lib_dir" ]]; then
      lib_arg=(--lib-dir "$lib_dir")
    fi

    chmod +x "${runner_dir}/kardome_runner" 2>/dev/null || true

    uv run python ./.github/scripts/ci_driver.py upload-runner \
      --bucket "$GCS_BUCKET" \
      --bucket-prefix "$BMT_BUCKET_PREFIX" \
      --runner-dir "$runner_dir" \
      "${lib_arg[@]}" \
      --project "$project" \
      --preset "$preset" \
      --source-ref "$source_ref"
    ;;

  warn-upload-failed)
    project="${PROJECT:-unknown-project}"
    preset="${PRESET:-unknown-preset}"
    echo "::warning::Runner upload failed for ${project} (${preset}). BMT will continue with other runners."
    ;;

  record-uploaded-project-marker)
    require_cmd gcloud
    project="${PROJECT:-}"
    run_id="$(current_run_id)"

    if [[ -z "$project" ]]; then
      echo "::error::PROJECT is required"
      exit 1
    fi

    root="$(runtime_root)"
    echo '{}' | gcloud storage cp - "${root}/_workflow/uploaded/${run_id}/${project}.json"
    ;;

  resolve-uploaded-projects)
    require_cmd gcloud
    require_cmd jq
    run_id="$(current_run_id)"
    root="$(runtime_root)"
    prefix="${root}/_workflow/uploaded/${run_id}/"

    if gcloud storage ls "$prefix" 2>/dev/null | grep -q '\.json$'; then
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
    ;;

  filter-supported-matrix)
    require_cmd jq
    runner_matrix="${RUNNER_MATRIX:-}"
    full_matrix="${FULL_MATRIX:-}"
    accepted_projects="${ACCEPTED_PROJECTS:-[]}"

    if [[ -z "$runner_matrix" || -z "$full_matrix" ]]; then
      echo "::error::RUNNER_MATRIX and FULL_MATRIX are required"
      exit 1
    fi

    if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
      echo "::error::GITHUB_OUTPUT is not set"
      exit 1
    fi

    echo "$runner_matrix" > /tmp/runner_matrix.json
    echo "$full_matrix" > /tmp/full.json
    echo "$accepted_projects" > /tmp/accepted.json

    requested="$(jq -c '[.include[].project] | unique | sort' /tmp/runner_matrix.json)"
    supported="$(jq -c '[.include[].project] | unique | sort' /tmp/full.json)"
    unsupported="$(jq -cn --argjson requested "$requested" --argjson supported "$supported" '$requested - $supported')"

    while IFS= read -r proj; do
      [[ -z "$proj" ]] && continue
      echo "::warning::Project '$proj' has no BMT config in this repo; no BMT leg will run for it."
    done < <(echo "$unsupported" | jq -r '.[]')

    filtered="$(jq -c --slurpfile acc /tmp/accepted.json '.include = [.include[] | select(.project as $p | $acc[0] | index($p))]' /tmp/full.json)"

    {
      echo "matrix<<EOMATRIX"
      echo "$filtered"
      echo "EOMATRIX"
    } >>"$GITHUB_OUTPUT"

    supported_legs="$(echo "$full_matrix" | jq '.include | length')"
    legs="$(echo "$filtered" | jq '.include | length')"

    if [[ "$supported_legs" -eq 0 ]]; then
      echo "has_legs=false" >>"$GITHUB_OUTPUT"
      echo "::warning::No supported BMT projects in requested runner set; skipping BMT trigger/VM run."
      exit 0
    fi

    if [[ "$legs" -eq 0 ]]; then
      echo "::error::Supported BMT projects exist, but no supported runner upload succeeded; cannot trigger BMT."
      exit 1
    fi

    echo "has_legs=true" >>"$GITHUB_OUTPUT"
    echo "::notice::Triggering BMT for ${legs} leg(s) (supported runners only)."
    ;;

  summarize-matrix-handshake)
    require_cmd jq
    runner_matrix="${RUNNER_MATRIX:-}"
    accepted="${ACCEPTED:-[]}"
    filtered_matrix="${FILTERED_MATRIX:-}"

    if [[ -z "$runner_matrix" || -z "$filtered_matrix" ]]; then
      echo "::error::RUNNER_MATRIX and FILTERED_MATRIX are required"
      exit 1
    fi
    if [[ -z "${GITHUB_STEP_SUMMARY:-}" ]]; then
      echo "::error::GITHUB_STEP_SUMMARY is not set"
      exit 1
    fi

    echo "$runner_matrix" > /tmp/runner_matrix.json
    echo "$filtered_matrix" > /tmp/filtered_matrix.json

    requested="$(jq -c '[.include[].project] | unique | sort' /tmp/runner_matrix.json)"
    bmt_legs="$(jq -c '[.include[].project] | unique | sort' /tmp/filtered_matrix.json)"

    {
      echo "## BMT Matrix Handshake"
      echo
      echo "| Project | Runner uploaded | BMT leg | Status |"
      echo "|---------|----------------|---------|--------|"
    } >>"$GITHUB_STEP_SUMMARY"

    while IFS= read -r proj; do
      [[ -z "$proj" ]] && continue
      if echo "$accepted" | jq -e --arg p "$proj" 'index($p)' >/dev/null; then
        up="yes"
      else
        up="skipped"
      fi

      if echo "$bmt_legs" | jq -e --arg p "$proj" 'index($p)' >/dev/null; then
        leg="yes"
        status="Will run"
      else
        leg="-"
        if [[ "$up" == "skipped" ]]; then
          status="Upload failed/warning"
        else
          status="No BMT config"
        fi
      fi

      echo "| ${proj} | ${up} | ${leg} | ${status} |" >>"$GITHUB_STEP_SUMMARY"
    done < <(echo "$requested" | jq -r '.[]')

    {
      echo
      echo "**Runners uploaded (supported):** $(echo "$accepted" | jq 'length')"
      echo "**BMT legs to run:** $(echo "$bmt_legs" | jq 'length')"
    } >>"$GITHUB_STEP_SUMMARY"
    ;;

  preflight-trigger-queue)
    require_cmd gcloud
    run_id="$(current_run_id)"
    root="$(runtime_root)"
    runs_prefix="${root}/triggers/runs/"
    current_uri="${runs_prefix}${run_id}.json"

    if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
      echo "::error::GITHUB_OUTPUT is not set"
      exit 1
    fi

    echo "restart_vm=false" >>"$GITHUB_OUTPUT"
    echo "stale_cleanup_count=0" >>"$GITHUB_OUTPUT"

    mapfile -t existing < <(gcloud storage ls "$runs_prefix" 2>/dev/null | sed '/\/$/d' | grep '\.json$' || true)
    blocking=()
    for uri in "${existing[@]}"; do
      [[ "$uri" == "$current_uri" ]] && continue
      blocking+=("$uri")
    done

    {
      echo "## Runtime Trigger Preflight"
      echo
      echo "- Runtime root: \`${root}\`"
      echo "- Existing trigger files: **${#existing[@]}**"
      echo "- Blocking stale trigger files: **${#blocking[@]}**"
    } >>"$GITHUB_STEP_SUMMARY"

    if [[ "${#blocking[@]}" -eq 0 ]]; then
      echo "- Action: no stale trigger cleanup required." >>"$GITHUB_STEP_SUMMARY"
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
    ;;

  write-run-trigger)
    require_cmd uv
    matrix_json="${FILTERED_MATRIX_JSON:-}"
    run_context="${RUN_CONTEXT:-dev}"
    head_event="${HEAD_EVENT:-}"
    pr_number="${PR_NUMBER:-}"
    config_root="${CONFIG_ROOT:-remote/code}"

    if [[ -z "$matrix_json" ]]; then
      echo "::error::FILTERED_MATRIX_JSON is required"
      exit 1
    fi

    args=(
      ./.github/scripts/ci_driver.py trigger
      --config-root "$config_root"
      --bucket "$GCS_BUCKET"
      --bucket-prefix "$BMT_BUCKET_PREFIX"
      --matrix-json "$matrix_json"
      --run-context "$run_context"
    )

    if [[ "$head_event" == "pull_request" && -n "$pr_number" ]]; then
      args+=(--pr-number "$pr_number")
    fi

    uv run python "${args[@]}"
    ;;

  force-clean-vm-restart)
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
    ;;

  show-handshake-guidance)
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
      echo "- **GCS:** \`gcloud storage cat \"${ack_uri}\"\` (after VM writes ack)"
      echo "- **VM serial output:** \`gcloud compute instances get-serial-port-output ${BMT_VM_NAME} --zone=${GCP_ZONE}\`"
      echo "- **Local TUI monitor:** \`just monitor --run-id ${run_id}\` or \`uv run python devtools/bmt_monitor.py --run-id ${run_id} --bucket ${GCS_BUCKET}\`"
    } >>"$GITHUB_STEP_SUMMARY"
    ;;

  wait-handshake)
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

    uv run python ./.github/scripts/ci_driver.py wait-handshake \
      --bucket "$GCS_BUCKET" \
      --bucket-prefix "$BMT_BUCKET_PREFIX" \
      --workflow-run-id "$run_id" \
      --timeout-sec "$timeout" \
      --poll-interval-sec 5
    ;;

  wait-verdicts)
    require_cmd uv
    manifest="${TRIGGER_MANIFEST:-}"
    timeout="${BMT_VERDICT_TIMEOUT_SEC:-1800}"
    poll_interval="${BMT_VERDICT_POLL_INTERVAL_SEC:-30}"
    config_root="${CONFIG_ROOT:-remote/code}"

    if [[ -z "$manifest" ]]; then
      echo "::error::TRIGGER_MANIFEST is required"
      exit 1
    fi

    uv run python ./.github/scripts/ci_driver.py wait \
      --manifest "$manifest" \
      --config-root "$config_root" \
      --bucket "$GCS_BUCKET" \
      --bucket-prefix "$BMT_BUCKET_PREFIX" \
      --timeout-sec "$timeout" \
      --poll-interval-sec "$poll_interval"
    ;;

  handshake-timeout-diagnostics)
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
    ;;

  show-handshake-summary)
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
    ;;

  post-pending-status)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    head_sha="${HEAD_SHA:-}"
    github_token="${GITHUB_TOKEN:-}"
    context="${BMT_STATUS_CONTEXT:-BMT Gate}"
    description="${BMT_DESCRIPTION_PENDING:-BMT running on VM; status will update when complete.}"
    if [[ -z "$repository" || -z "$head_sha" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, HEAD_SHA, and GITHUB_TOKEN are required"
      exit 1
    fi

    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/statuses/${head_sha}" \
      -d "$(jq -n --arg c "$context" --arg d "$description" '{state:"pending",context:$c,description:$d}')"
    ;;

  post-final-status-from-decision)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    head_sha="${HEAD_SHA:-}"
    github_token="${GITHUB_TOKEN:-}"
    context="${BMT_STATUS_CONTEXT:-BMT Gate}"
    decision="${DECISION:-}"
    pass_count="${PASS_COUNT:-0}"
    warning_count="${WARNING_COUNT:-0}"
    fail_count="${FAIL_COUNT:-0}"
    timeout_count="${TIMEOUT_COUNT:-0}"

    if [[ -z "$repository" || -z "$head_sha" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, HEAD_SHA, and GITHUB_TOKEN are required"
      exit 1
    fi

    state="failure"
    description="BMT decision unavailable; check workflow logs."
    case "$decision" in
      accepted)
        state="success"
        description="BMT passed (${pass_count} pass, ${warning_count} warning)."
        ;;
      accepted_with_warnings)
        state="success"
        description="BMT passed with warnings (${pass_count} pass, ${warning_count} warning)."
        ;;
      rejected)
        state="failure"
        description="BMT failed (${fail_count} fail, ${timeout_count} timeout)."
        ;;
      timeout)
        state="failure"
        description="BMT timed out (${timeout_count} timeout)."
        ;;
      "")
        state="failure"
        description="BMT verdict collection failed; check workflow logs."
        ;;
      *)
        state="failure"
        description="BMT decision '${decision}' is unsupported; check workflow logs."
        ;;
    esac
    description="${description:0:140}"
    target_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-${repository}}/actions/runs/${GITHUB_RUN_ID:-}"

    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/statuses/${head_sha}" \
      -d "$(jq -n --arg c "$context" --arg d "$description" --arg s "$state" --arg t "$target_url" '{state:$s,context:$c,description:$d,target_url:$t}')"
    ;;

  post-started-pending)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    head_sha="${HEAD_SHA:-}"
    github_token="${GITHUB_TOKEN:-}"
    context="${BMT_STATUS_CONTEXT:-BMT Gate}"
    if [[ -z "$repository" || -z "$head_sha" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, HEAD_SHA, and GITHUB_TOKEN are required"
      exit 1
    fi

    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/statuses/${head_sha}" \
      -d "$(jq -n --arg c "$context" --arg d "BMT started; waiting for VM handshake…" '{state:"pending",context:$c,description:$d}')"
    ;;

  post-skipped-success-status)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    head_sha="${HEAD_SHA:-}"
    github_token="${GITHUB_TOKEN:-}"
    context="${BMT_STATUS_CONTEXT:-BMT Gate}"
    if [[ -z "$repository" || -z "$head_sha" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, HEAD_SHA, and GITHUB_TOKEN are required"
      exit 1
    fi

    reason="No supported BMT projects in requested set; no BMT legs were run."
    reason="${reason:0:140}"
    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/statuses/${head_sha}" \
      -d "$(jq -n --arg c "$context" --arg d "$reason" '{state:"success",context:$c,description:$d}')"
    ;;

  post-failure-status)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    head_sha="${HEAD_SHA:-}"
    github_token="${GITHUB_TOKEN:-}"
    vm_handshake_result="${VM_HANDSHAKE_RESULT:-}"
    run_id="${RUN_ID:-}"
    context="${BMT_STATUS_CONTEXT:-BMT Gate}"
    if [[ -z "$repository" || -z "$head_sha" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, HEAD_SHA, and GITHUB_TOKEN are required"
      exit 1
    fi

    reason="BMT workflow failed. Check Actions logs."
    if [[ "$vm_handshake_result" == "failure" ]]; then
      reason="VM handshake timeout. Actions logs; local: just gcs-trigger ${run_id} just vm-serial"
    fi
    reason="${reason:0:140}"

    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/statuses/${head_sha}" \
      -d "$(jq -n --arg c "$context" --arg d "$reason" '{state:"failure",context:$c,description:$d}')"
    ;;

  post-failure-pr-comment)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    pr_number="${PR_NUMBER:-}"
    github_token="${GITHUB_TOKEN:-}"
    vm_handshake_result="${VM_HANDSHAKE_RESULT:-}"
    if [[ -z "$repository" || -z "$pr_number" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, PR_NUMBER, and GITHUB_TOKEN are required"
      exit 1
    fi

    if [[ "$vm_handshake_result" == "failure" ]]; then
      body=$'## BMT result: Did not run\n\nThe test run did not complete because the test machine did not respond in time. For details, open the **Actions** tab and look at the failed workflow run.'
    else
      body=$'## BMT result: Did not run\n\nThe test run did not complete. For details, open the **Actions** tab and look at the failed workflow run.'
    fi
    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/issues/${pr_number}/comments" \
      -d "$(jq -n --arg body "$body" '{body:$body}')"
    ;;

  cleanup-failed-trigger-artifacts)
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
    ;;

  stop-vm-best-effort)
    require_cmd gcloud
    set +e
    gcloud compute instances stop "$BMT_VM_NAME" \
      --zone "$GCP_ZONE" \
      --project "$GCP_PROJECT" >/dev/null 2>&1 || true
    ;;

  post-no-context-failure-status)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    head_sha="${HEAD_SHA:-}"
    github_token="${GITHUB_TOKEN:-}"
    context="${BMT_STATUS_CONTEXT:-BMT Gate}"
    if [[ -z "$repository" || -z "$head_sha" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, HEAD_SHA, and GITHUB_TOKEN are required"
      exit 1
    fi

    reason="BMT workflow failed before context. Check Actions logs."
    reason="${reason:0:140}"
    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/statuses/${head_sha}" \
      -d "$(jq -n --arg c "$context" --arg d "$reason" '{state:"failure",context:$c,description:$d}')"
    ;;

  post-no-context-pr-comment)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    pr_number="${PR_NUMBER:-}"
    github_token="${GITHUB_TOKEN:-}"
    if [[ -z "$repository" || -z "$pr_number" || -z "$github_token" ]]; then
      echo "::error::REPOSITORY, PR_NUMBER, and GITHUB_TOKEN are required"
      exit 1
    fi

    body=$'## BMT result: Did not run\n\nThe test workflow failed before tests could start. For details, open the **Actions** tab for this run.'
    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/issues/${pr_number}/comments" \
      -d "$(jq -n --arg body "$body" '{body:$body}')"
    ;;

  *)
    usage
    exit 1
    ;;
esac

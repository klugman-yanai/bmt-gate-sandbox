#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/github_api.sh"

HEAD_SHA_RESOLVED=""
HEAD_BRANCH_RESOLVED=""
HEAD_EVENT_RESOLVED=""
PR_NUMBER_RESOLVED=""

usage() {
  cat <<'USAGE'
Usage: .github/bmt/scripts/ci_workflow.sh <command>

Commands:
  parse-presets
  stage-release-runner
  compute-preset-info
  resolve-head-context
  dispatch-bmt
  handoff-dispatch-bmt
  post-trigger-failure-status
  write-handoff-dispatch-summary
USAGE
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "::error::Required command not found: $1"
    exit 1
  fi
}

resolve_head_context() {
  local event_name="${EVENT_NAME:-}"
  if [[ -z "$event_name" ]]; then
    echo "::error::EVENT_NAME is required"
    exit 1
  fi

  if [[ "$event_name" == "pull_request" || "$event_name" == "pull_request_target" ]]; then
    HEAD_SHA_RESOLVED="${PR_HEAD_SHA:-}"
    HEAD_BRANCH_RESOLVED="${PR_HEAD_REF:-}"
    HEAD_EVENT_RESOLVED="pull_request"
    PR_NUMBER_RESOLVED="${PR_NUMBER:-}"
  else
    HEAD_SHA_RESOLVED="${DEFAULT_HEAD_SHA:-}"
    HEAD_BRANCH_RESOLVED="${DEFAULT_HEAD_BRANCH:-}"
    HEAD_EVENT_RESOLVED="push"
    PR_NUMBER_RESOLVED=""
  fi

  if [[ -z "$HEAD_SHA_RESOLVED" || -z "$HEAD_BRANCH_RESOLVED" ]]; then
    echo "::error::Failed to resolve head context (HEAD_SHA/HEAD_BRANCH empty)"
    exit 1
  fi
}

write_head_context_output() {
  if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
    echo "::error::GITHUB_OUTPUT is not set"
    exit 1
  fi
  {
    echo "head_sha=${HEAD_SHA_RESOLVED}"
    echo "head_branch=${HEAD_BRANCH_RESOLVED}"
    echo "head_event=${HEAD_EVENT_RESOLVED}"
    echo "pr_number=${PR_NUMBER_RESOLVED}"
  } >>"$GITHUB_OUTPUT"
}

dispatch_bmt_request() {
  local repository="$1"
  local app_token="$2"
  local head_branch="$3"
  local ci_run_id="$4"
  local head_sha="$5"
  local head_event="$6"
  local pr_number="$7"
  local ref=""
  local url=""
  local body=""

  if [[ -z "$repository" || -z "$app_token" || -z "$head_branch" || -z "$ci_run_id" || -z "$head_sha" ]]; then
    echo "::error::REPOSITORY, APP_TOKEN, HEAD_BRANCH, CI_RUN_ID, and HEAD_SHA are required"
    exit 1
  fi

  ref="refs/heads/${head_branch}"
  url="https://api.github.com/repos/${repository}/actions/workflows/bmt.yml/dispatches"
  body="$(jq -n \
    --arg ref "$ref" \
    --arg run_id "$ci_run_id" \
    --arg head_sha "$head_sha" \
    --arg head_branch "$head_branch" \
    --arg head_event "$head_event" \
    --arg pr_number "$pr_number" \
    '{ref: $ref, inputs: {ci_run_id: $run_id, head_sha: $head_sha, head_branch: $head_branch, head_event: $head_event, pr_number: $pr_number}}')"

  gh_api_request "POST" "$url" "$app_token" "$body"
}

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi
shift || true

case "$cmd" in
  parse-presets)
    require_cmd uv
    uv sync --project .github/bmt
    BMT_OUTPUT_FORMAT="ci" \
    BMT_OUTPUT_KEY="presets" \
    BMT_PROJECTS="${BMT_PROJECTS:-all}" \
      uv run --project .github/bmt bmt parse-release-runners
    ;;

  stage-release-runner)
    require_cmd jq
    cfg="${MATRIX_CONFIGURE:-}"
    if [[ -z "$cfg" ]]; then
      echo "::error::MATRIX_CONFIGURE is required"
      exit 1
    fi

    if [[ "$cfg" == *"_gcc_Release"* && "$cfg" != *"xtensa"* && "$cfg" != *"hexagon"* ]]; then
      binary_dir="$(jq -r --arg name "$cfg" '.configurePresets[] | select(.name==$name) | .binaryDir' CMakePresets.json | sed 's|[$]{sourceDir}|.|')"
      project="$(echo "$cfg" | sed 's/_gcc_Release$//' | tr '[:upper:]' '[:lower:]')"
      mkdir -p "$binary_dir/Runners" "$binary_dir/Kardome"
      if [[ -f "$binary_dir/Runners/kardome_runner" ]]; then
        echo "Using existing runner from $binary_dir/Runners (build/ layout)"
      elif [[ -f "remote/runtime/sk/runners/sk_gcc_release/kardome_runner" && "$project" == "sk" ]]; then
        cp -v remote/runtime/sk/runners/sk_gcc_release/kardome_runner "$binary_dir/Runners/"
        [[ -f "remote/runtime/sk/runners/lib/libKardome.so" ]] && cp -v remote/runtime/sk/runners/lib/libKardome.so "$binary_dir/Kardome/" || true
        chmod +x "$binary_dir/Runners/kardome_runner"
        echo "Using real runner from remote/runtime/sk/runners/ (production-like artifact)"
      else
        echo "::warning::No real runner for $project; creating placeholder for path-only test"
        touch "$binary_dir/Runners/kardome_runner" "$binary_dir/Kardome/libKardome.so"
        chmod +x "$binary_dir/Runners/kardome_runner"
      fi
    fi
    ;;

  compute-preset-info)
    require_cmd jq
    cfg="${MATRIX_CONFIGURE:-}"
    if [[ -z "$cfg" ]]; then
      echo "::error::MATRIX_CONFIGURE is required"
      exit 1
    fi

    preset="$(echo "$cfg" | tr '[:upper:]' '[:lower:]')"
    project="$(echo "$cfg" | sed 's/_gcc_Release$//' | tr '[:upper:]' '[:lower:]')"
    binary_dir="$(jq -r --arg name "$cfg" '.configurePresets[] | select(.name==$name) | .binaryDir' CMakePresets.json | sed 's|[$]{sourceDir}|.|')"

    if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
      echo "::error::GITHUB_OUTPUT is not set"
      exit 1
    fi

    echo "preset=$preset" >>"$GITHUB_OUTPUT"
    echo "project=$project" >>"$GITHUB_OUTPUT"
    echo "runners_dir=${binary_dir}/Runners" >>"$GITHUB_OUTPUT"
    echo "lib_dir=${binary_dir}/Kardome" >>"$GITHUB_OUTPUT"
    ;;

  resolve-head-context)
    resolve_head_context
    write_head_context_output
    ;;

  dispatch-bmt)
    require_cmd jq
    repository="${REPOSITORY:-}"
    app_token="${APP_TOKEN:-}"
    head_branch="${HEAD_BRANCH:-}"
    ci_run_id="${CI_RUN_ID:-}"
    head_sha="${HEAD_SHA:-}"
    head_event="${HEAD_EVENT:-push}"
    pr_number="${PR_NUMBER:-}"

    dispatch_bmt_request "$repository" "$app_token" "$head_branch" "$ci_run_id" "$head_sha" "$head_event" "$pr_number"
    ;;

  handoff-dispatch-bmt)
    require_cmd jq
    resolve_head_context

    repository="${REPOSITORY:-}"
    app_token="${APP_TOKEN:-}"
    ci_run_id="${CI_RUN_ID:-}"
    dispatch_bmt_request \
      "$repository" \
      "$app_token" \
      "$HEAD_BRANCH_RESOLVED" \
      "$ci_run_id" \
      "$HEAD_SHA_RESOLVED" \
      "$HEAD_EVENT_RESOLVED" \
      "$PR_NUMBER_RESOLVED"

    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
      write_head_context_output
    fi
    ;;

  post-trigger-failure-status)
    repository="${REPOSITORY:-}"
    github_token="${GITHUB_TOKEN:-}"
    head_sha="${HEAD_SHA:-}"
    event_name="${EVENT_NAME:-push}"
    pr_number="${PR_NUMBER:-}"
    context="${BMT_STATUS_CONTEXT:-BMT Gate}"

    if [[ -z "$repository" || -z "$github_token" || -z "$head_sha" ]]; then
      echo "::error::REPOSITORY, GITHUB_TOKEN, and HEAD_SHA are required"
      exit 1
    fi

    gh_post_status \
      "$repository" \
      "$head_sha" \
      "$github_token" \
      "failure" \
      "$context" \
      "Trigger BMT failed. Check Actions logs."

    if [[ ( "$event_name" == "pull_request" || "$event_name" == "pull_request_target" ) && -n "$pr_number" ]]; then
      body=$'## BMT result: Did not run\n\nThe test run could not be started. For details, open the **Actions** tab for this PR.'
      gh_post_pr_comment "$repository" "$pr_number" "$github_token" "$body"
    fi
    ;;

  write-handoff-dispatch-summary)
    repository="${REPOSITORY:-}"
    event_name="${EVENT_NAME:-push}"
    head_sha="${HEAD_SHA:-}"
    head_branch="${HEAD_BRANCH:-}"
    head_event="${HEAD_EVENT:-push}"
    pr_number="${PR_NUMBER:-}"
    ci_run_id="${CI_RUN_ID:-}"
    dispatch_outcome="${DISPATCH_OUTCOME:-unknown}"
    server_url="${GITHUB_SERVER_URL:-https://github.com}"
    run_url=""
    pr_url=""
    state_line=""

    if [[ -n "$repository" && -n "$ci_run_id" ]]; then
      run_url="${server_url}/${repository}/actions/runs/${ci_run_id}"
    fi
    if [[ -n "$repository" && -n "$pr_number" ]]; then
      pr_url="${server_url}/${repository}/pull/${pr_number}"
    fi

    if [[ "$dispatch_outcome" == "success" ]]; then
      state_line="Handoff dispatch complete: bmt.yml workflow was triggered."
    else
      state_line="Handoff dispatch failed: bmt.yml workflow was not triggered."
    fi

    {
      echo "## BMT Handoff Dispatch Summary"
      echo
      echo "$state_line"
      echo
      echo "- Repository: \`${repository:-unknown}\`"
      echo "- Event: \`${event_name}\` (head event: \`${head_event}\`)"
      echo "- Head branch: \`${head_branch:-unknown}\`"
      echo "- Head SHA: \`${head_sha:-unknown}\`"
      echo "- Dispatch outcome: \`${dispatch_outcome}\`"
      if [[ -n "$run_url" ]]; then
        echo "- Workflow run: [Open run](${run_url})"
      fi
      if [[ -n "$pr_url" ]]; then
        echo "- PR: [#${pr_number}](${pr_url})"
      else
        echo "- PR: (not applicable)"
      fi
      echo
      echo "This workflow reports handoff dispatch health only."
      echo "Final BMT outcome is posted by the VM to PR checks/comments."
    } >>"${GITHUB_STEP_SUMMARY:-/dev/stdout}"
    ;;

  *)
    usage
    exit 1
    ;;
esac

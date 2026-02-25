#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: .github/scripts/workflows/ci_workflow.sh <command>

Commands:
  parse-presets
  stage-release-runner
  compute-preset-info
  resolve-head-context
  dispatch-bmt
  post-trigger-failure-status
USAGE
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "::error::Required command not found: $1"
    exit 1
  fi
}

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi
shift || true

case "$cmd" in
  parse-presets)
    require_cmd jq
    allowed_raw="${BMT_PROJECTS:-all release runners}"
    allowed_norm="$(echo "$allowed_raw" | tr '[:upper:]' '[:lower:]' | xargs)"

    if [[ -z "$allowed_norm" || "$allowed_norm" == "all" || "$allowed_norm" == "*" || "$allowed_norm" == "all release runners" || "$allowed_norm" == "all-release-runners" || "$allowed_norm" == "all_release_runners" ]]; then
      allowed_json='null'
    else
      allowed_json="$(echo "$allowed_raw" | jq -Rc 'split(",") | map(gsub("^ +| +$"; "") | ascii_downcase) | map(select(length>0))')"
    fi

    presets="$(jq -c --argjson allowed "$allowed_json" '
      [ .configurePresets[]
        | select(.name | test("_gcc_Release$"))
        | select(.name | test("xtensa|hexagon") | not)
        | (.name | sub("_gcc_Release$"; "") | ascii_downcase) as $proj
        | select($allowed == null or ($allowed | index($proj)))
        | { configure: .name, build: (.name + "-build"), short: .name }
      ] | unique_by(.configure)' CMakePresets.json)"

    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
      echo "presets=$presets" >>"$GITHUB_OUTPUT"
    fi
    echo "::notice::Building one job per project (BMT_PROJECTS=${allowed_raw}): $presets"
    ;;

  stage-release-runner)
    require_cmd jq
    cfg="${MATRIX_CONFIGURE:-}"
    if [[ -z "$cfg" ]]; then
      echo "::error::MATRIX_CONFIGURE is required"
      exit 1
    fi

    if [[ "$cfg" == *"_gcc_Release"* && "$cfg" != *"xtensa"* && "$cfg" != *"hexagon"* ]]; then
      binary_dir="$(jq -r --arg name "$cfg" '.configurePresets[] | select(.name==$name) | .binaryDir' CMakePresets.json | sed 's|\${sourceDir}|.|')"
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
    binary_dir="$(jq -r --arg name "$cfg" '.configurePresets[] | select(.name==$name) | .binaryDir' CMakePresets.json | sed 's|\${sourceDir}|.|')"

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
    event_name="${EVENT_NAME:-}"
    if [[ -z "$event_name" ]]; then
      echo "::error::EVENT_NAME is required"
      exit 1
    fi
    if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
      echo "::error::GITHUB_OUTPUT is not set"
      exit 1
    fi

    if [[ "$event_name" == "pull_request" ]]; then
      echo "head_sha=${PR_HEAD_SHA:-}" >>"$GITHUB_OUTPUT"
      echo "head_branch=${PR_HEAD_REF:-}" >>"$GITHUB_OUTPUT"
      echo "head_event=pull_request" >>"$GITHUB_OUTPUT"
      echo "pr_number=${PR_NUMBER:-}" >>"$GITHUB_OUTPUT"
    else
      echo "head_sha=${DEFAULT_HEAD_SHA:-}" >>"$GITHUB_OUTPUT"
      echo "head_branch=${DEFAULT_HEAD_BRANCH:-}" >>"$GITHUB_OUTPUT"
      echo "head_event=push" >>"$GITHUB_OUTPUT"
      echo "pr_number=" >>"$GITHUB_OUTPUT"
    fi
    ;;

  dispatch-bmt)
    require_cmd jq
    require_cmd curl
    repository="${REPOSITORY:-}"
    app_token="${APP_TOKEN:-}"
    head_branch="${HEAD_BRANCH:-}"
    ci_run_id="${CI_RUN_ID:-}"
    head_sha="${HEAD_SHA:-}"
    head_event="${HEAD_EVENT:-push}"
    pr_number="${PR_NUMBER:-}"

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

    http_code="$(curl -sS -w '%{http_code}' -o /tmp/dispatch_resp -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${app_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "$url" -d "$body")"

    if [[ "$http_code" != "204" ]]; then
      echo "Workflow dispatch returned HTTP ${http_code}. Response:"
      cat /tmp/dispatch_resp
      exit 1
    fi
    ;;

  post-trigger-failure-status)
    require_cmd jq
    require_cmd curl
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

    curl -sS -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer ${github_token}" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/${repository}/statuses/${head_sha}" \
      -d "$(jq -n --arg c "$context" --arg d "Trigger BMT failed. Check Actions logs." '{state:"failure",context:$c,description:$d}')"

    if [[ "$event_name" == "pull_request" && -n "$pr_number" ]]; then
      body=$'## BMT result: Did not run\n\nThe test run could not be started. For details, open the **Actions** tab for this PR.'
      curl -sS -X POST \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer ${github_token}" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/${repository}/issues/${pr_number}/comments" \
        -d "$(jq -n --arg body "$body" '{body:$body}')"
    fi
    ;;

  *)
    usage
    exit 1
    ;;
esac

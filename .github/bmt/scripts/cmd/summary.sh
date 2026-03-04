#!/usr/bin/env bash

bmt_cmd_write_handoff_summary() {
  local mode repository head_sha head_branch head_event pr_number
  local routing_decision runner_matrix accepted_projects filtered_matrix
  local trigger_written vm_started handshake_ok handshake_uri
  local handoff_state_line failure_reason
  local run_url repo_url pr_url
  local requested_count uploaded_count legs_planned

  require_cmd jq

  mode="${MODE:-}"
  repository="${REPOSITORY:-${GITHUB_REPOSITORY:-}}"
  head_sha="${HEAD_SHA:-}"
  head_branch="${HEAD_BRANCH:-}"
  head_event="${HEAD_EVENT:-}"
  pr_number="${PR_NUMBER:-}"

  routing_decision="${ROUTING_DECISION:-unknown}"
  runner_matrix="${RUNNER_MATRIX:-{\"include\":[]}}"
  accepted_projects="${ACCEPTED_PROJECTS:-[]}"
  filtered_matrix="${FILTERED_MATRIX:-{\"include\":[]}}"

  trigger_written="${TRIGGER_WRITTEN:-false}"
  vm_started="${VM_STARTED:-false}"
  handshake_ok="${HANDSHAKE_OK:-false}"
  handshake_uri="${HANDSHAKE_URI:-}"

  handoff_state_line="${HANDOFF_STATE_LINE:-}"
  failure_reason="${FAILURE_REASON:-}"

  if [[ -z "${GITHUB_STEP_SUMMARY:-}" ]]; then
    echo "::error::GITHUB_STEP_SUMMARY is not set"
    exit 1
  fi

  repo_url="${GITHUB_SERVER_URL:-https://github.com}/${repository}"
  run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-${repository}}/actions/runs/${GITHUB_RUN_ID:-}"
  pr_url=""
  if [[ -n "$pr_number" ]]; then
    pr_url="${repo_url}/pull/${pr_number}"
  fi

  requested_count="$(echo "$runner_matrix" | jq '[.include[]?.project] | unique | length' 2>/dev/null || echo 0)"
  uploaded_count="$(echo "$accepted_projects" | jq 'length' 2>/dev/null || echo 0)"
  legs_planned="$(echo "$filtered_matrix" | jq '[.include[]?] | length' 2>/dev/null || echo 0)"

  if [[ -z "$handoff_state_line" ]]; then
    case "$mode" in
      run_success)
        handoff_state_line="Handoff complete: VM acknowledged trigger."
        ;;
      skip)
        handoff_state_line="Handoff complete: no supported uploaded legs to hand off."
        ;;
      failure)
        handoff_state_line="Handoff failed: VM did not acknowledge trigger."
        ;;
      *)
        handoff_state_line="Handoff state unavailable. Check this workflow run."
        ;;
    esac
  fi

  {
    echo "## BMT Handoff Summary"
    echo
    echo "- ${handoff_state_line}"
    if [[ -n "$failure_reason" ]]; then
      echo "- Failure reason: ${failure_reason}"
    fi
    echo
    echo "| Signal | Value |"
    echo "|---|---|"
    echo "| repository | \`${repository}\` |"
    echo "| workflow_run | [Open run](${run_url}) |"
    if [[ -n "$pr_url" ]]; then
      echo "| pr | [#${pr_number}](${pr_url}) |"
    else
      echo "| pr | n/a |"
    fi
    echo "| head_event | \`${head_event}\` |"
    echo "| head_branch | \`${head_branch}\` |"
    echo "| head_sha | \`${head_sha}\` |"
    echo "| route | \`${routing_decision}\` |"
    echo "| mode | \`${mode}\` |"
    echo "| trigger_written | \`${trigger_written}\` |"
    echo "| vm_started | \`${vm_started}\` |"
    echo "| handshake_ok | \`${handshake_ok}\` |"
    if [[ -n "$handshake_uri" ]]; then
      echo "| handshake_uri | \`${handshake_uri}\` |"
    fi
    echo "| requested_projects | \`${requested_count}\` |"
    echo "| uploaded_projects | \`${uploaded_count}\` |"
    echo "| legs_handed_off | \`${legs_planned}\` |"
    echo "| merge_gate_context | \`${BMT_STATUS_CONTEXT:-BMT Gate}\` |"
  } >>"$GITHUB_STEP_SUMMARY"
}

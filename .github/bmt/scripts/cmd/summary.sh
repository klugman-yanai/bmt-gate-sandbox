#!/usr/bin/env bash

bmt_cmd_write_handoff_summary() {
  local mode repository head_sha head_branch head_event pr_number
  local routing_decision runner_matrix accepted_projects filtered_matrix
  local trigger_written vm_started handshake_ok handshake_uri
  local handoff_state_line failure_reason
  local run_url repo_url pr_url
  local requested_count uploaded_count legs_planned requested_projects

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
  requested_projects="$(echo "$runner_matrix" | jq -r '[.include[]?.project] | unique | sort | join(", ")' 2>/dev/null || echo "")"

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
    echo "### 1) Handoff Overview"
    echo "- Repository: \`${repository}\`"
    echo "- Head SHA: \`${head_sha}\`"
    echo "- Head branch: \`${head_branch}\`"
    echo "- Head event: \`${head_event}\`"
    echo "- Workflow run: [Open run](${run_url})"
    if [[ -n "$pr_url" ]]; then
      echo "- PR: [#${pr_number}](${pr_url})"
    else
      echo "- PR: _(not a pull request run)_"
    fi
    echo
    echo "### 2) Routing Decision"
    echo "- Selected path: \`${routing_decision}\`"
    case "$routing_decision" in
      run)
        echo "- Reason: supported legs exist and at least one supported runner upload succeeded."
        ;;
      skip_no_legs)
        echo "- Reason: no supported uploaded legs to hand off."
        ;;
      *)
        echo "- Reason: path classification unavailable due to upstream failure."
        ;;
    esac
    echo
    echo "### 3) Delivery State"
    echo "- Trigger written: **${trigger_written}**"
    echo "- VM start invoked: **${vm_started}**"
    echo "- Handshake acknowledged: **${handshake_ok}**"
    if [[ -n "$handshake_uri" ]]; then
      echo "- Handshake URI: \`${handshake_uri}\`"
    fi
    echo "- Requested projects: **${requested_count}**"
    echo "- Uploaded supported projects: **${uploaded_count}**"
    echo "- Legs handed off: **${legs_planned}**"
    if [[ -n "$requested_projects" ]]; then
      echo "- Requested list: \`${requested_projects}\`"
    fi
    echo
    echo "### 4) Ownership Notice"
    echo "- This workflow validates **handoff only**."
    echo "- Handshake success means VM pickup only; final gate updates after VM execution completes."
    echo "- Runtime progress context: \`${BMT_RUNTIME_CONTEXT:-BMT Runtime}\` (non-gating)."
    echo "- Final merge gate context: \`${BMT_STATUS_CONTEXT:-BMT Gate}\`."
    echo "- BMT result is reported by the VM to **PR checks and PR comments**."
    echo "- ${handoff_state_line}"
    if [[ -n "$failure_reason" ]]; then
      echo "- Failure reason: ${failure_reason}"
    fi
    echo
    echo "### 5) Next Actions"
    if [[ -n "$pr_url" ]]; then
      echo "1. Open the PR: [#${pr_number}](${pr_url})"
      echo "2. Check PR **Checks** for VM-owned BMT status context."
      echo "3. Check PR **Comments** for VM-posted BMT outcome details."
    else
      echo "1. Open this workflow run and use dispatch inputs to locate the target commit/PR."
      echo "2. Verify commit checks for VM-owned BMT status context."
      echo "3. Check repository PR comments for VM-posted BMT outcome details."
    fi
    if [[ "$mode" == "failure" ]]; then
      echo "4. If handoff failed, inspect this run's diagnostics (trigger + handshake sections)."
    fi
  } >>"$GITHUB_STEP_SUMMARY"
}

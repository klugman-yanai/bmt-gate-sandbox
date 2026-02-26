#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/cmd/context.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/cmd/upload.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/cmd/trigger.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/cmd/handshake.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/cmd/failure.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/cmd/summary.sh"

usage() {
  cat <<'USAGE'
Usage: .github/scripts/workflows/bmt_workflow.sh <command>

Commands:
  emit-bmt-context
  validate-required-vars
  warn-artifact-missing
  upload-runner-to-gcs
  warn-upload-failed
  record-uploaded-project-marker
  resolve-uploaded-projects
  summarize-matrix-handshake
  preflight-trigger-queue
  write-run-trigger
  force-clean-vm-restart
  show-handshake-guidance
  wait-handshake
  handshake-timeout-diagnostics
  show-handshake-summary
  resolve-failure-context
  cleanup-failed-trigger-artifacts
  stop-vm-best-effort
  write-handoff-summary
USAGE
}

declare -A COMMAND_HANDLERS=(
  [emit-bmt-context]=bmt_cmd_emit_bmt_context
  [validate-required-vars]=bmt_cmd_validate_required_vars
  [warn-artifact-missing]=bmt_cmd_warn_artifact_missing
  [upload-runner-to-gcs]=bmt_cmd_upload_runner_to_gcs
  [warn-upload-failed]=bmt_cmd_warn_upload_failed
  [record-uploaded-project-marker]=bmt_cmd_record_uploaded_project_marker
  [resolve-uploaded-projects]=bmt_cmd_resolve_uploaded_projects
  [summarize-matrix-handshake]=bmt_cmd_summarize_matrix_handshake
  [preflight-trigger-queue]=bmt_cmd_preflight_trigger_queue
  [write-run-trigger]=bmt_cmd_write_run_trigger
  [force-clean-vm-restart]=bmt_cmd_force_clean_vm_restart
  [show-handshake-guidance]=bmt_cmd_show_handshake_guidance
  [wait-handshake]=bmt_cmd_wait_handshake
  [handshake-timeout-diagnostics]=bmt_cmd_handshake_timeout_diagnostics
  [show-handshake-summary]=bmt_cmd_show_handshake_summary
  [resolve-failure-context]=bmt_cmd_resolve_failure_context
  [cleanup-failed-trigger-artifacts]=bmt_cmd_cleanup_failed_trigger_artifacts
  [stop-vm-best-effort]=bmt_cmd_stop_vm_best_effort
  [write-handoff-summary]=bmt_cmd_write_handoff_summary
)

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi
shift || true

handler="${COMMAND_HANDLERS[$cmd]-}"
if [[ -z "$handler" ]]; then
  usage
  exit 1
fi

"$handler" "$@"

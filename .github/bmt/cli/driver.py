#!/usr/bin/env python3
"""BMT CI entrypoint. Each command reads its inputs from environment variables."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `cli` package resolves when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from . import gh_output
from .commands import (
    ci_workflow,
    load_env,
    matrix,
    trigger,
    upload_runner,
    vm,
    workflow,
    workflow_trigger,
)

COMMANDS = {
    "load-env": load_env.run_load_env,
    "matrix": matrix.run_build,
    "filter-supported-matrix": matrix.run_filter,
    "parse-release-runners": matrix.run_release_runners,
    "upload-runner": upload_runner.run,
    "select-available-vm": vm.run_select_available_vm,
    "start-vm": vm.run_start,
    "sync-vm-metadata": vm.run_sync_metadata,
    "wait-handshake": workflow.run_wait_handshake,
    # Workflow step commands (replace bmt_workflow.sh)
    "resolve-failure-context": workflow.run_resolve_failure_context,
    "filter-upload-matrix": workflow.run_filter_upload_matrix,
    "upload-runner-to-gcs": workflow.run_upload_runner_to_gcs,
    "resolve-uploaded-projects": workflow.run_resolve_uploaded_projects,
    "summarize-matrix-handshake": workflow.run_summarize_matrix_handshake,
    "check-superseded-pr-handoff": workflow.run_check_superseded_pr_handoff,
    "preflight-trigger-queue": workflow_trigger.run_preflight_trigger_queue,
    "write-run-trigger": trigger.run_trigger,
    "force-clean-vm-restart": workflow.run_force_clean_vm_restart,
    "handshake-timeout-diagnostics": workflow.run_handshake_timeout_diagnostics,
    "post-pending-status": workflow.run_post_pending_status,
    "post-handoff-timeout-status": workflow.run_post_handoff_timeout_status,
    "cleanup-failed-trigger-artifacts": workflow.run_cleanup_failed_trigger_artifacts,
    "write-handoff-summary": workflow.run_write_handoff_summary,
    # CI workflow (build-and-test.yml)
    "stage-release-runner": ci_workflow.run_stage_release_runner,
    "compute-preset-info": ci_workflow.run_compute_preset_info,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: driver.py <command>\nCommands: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    args = sys.argv[2:]
    COMMANDS[cmd]()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        gh_output.gh_error(str(exc))
        sys.exit(1)

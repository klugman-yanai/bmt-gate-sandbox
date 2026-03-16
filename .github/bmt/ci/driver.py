#!/usr/bin/env python3
"""BMT CI entrypoint. COMMANDS dict dispatch; each command reads inputs from environment."""

from __future__ import annotations

import sys
from collections.abc import Callable

from ci import config
from ci.actions import gh_error
from ci.handoff import HandoffManager
from ci.handshake import HandshakeManager
from ci.matrix import MatrixManager
from ci.preset import PresetManager
from ci.runner import RunnerManager
from ci.trigger import TriggerManager
from ci.vm import VmManager


def _load_env() -> None:
    config.load_env()


COMMANDS: dict[str, Callable[[], None]] = {
    "load-env": _load_env,
    "matrix": lambda: MatrixManager.from_env().build(),
    "filter-supported-matrix": lambda: MatrixManager.from_env().filter_supported(),
    "parse-release-runners": lambda: MatrixManager.from_env().parse_release_runners(),
    "upload-runner": lambda: RunnerManager.from_env().upload(),
    "select-available-vm": lambda: VmManager.from_env().select(),
    "start-vm": lambda: VmManager.from_env().start(),
    "sync-vm-metadata": lambda: VmManager.from_env().sync_metadata(),
    "write-context": lambda: HandoffManager.from_env().write_context(),
    "wait-watcher-ready": lambda: HandshakeManager.from_env().wait_watcher_ready(),
    "wait-handshake": lambda: HandshakeManager.from_env().wait(),
    "resolve-failure-context": lambda: HandoffManager.from_env().resolve_failure_context(),
    "filter-upload-matrix": lambda: RunnerManager.from_env().filter_upload_matrix(),
    "upload-runner-to-gcs": lambda: RunnerManager.from_env().upload_runner_to_gcs(),
    "validate-runner-in-repo": lambda: RunnerManager.from_env().validate_in_repo(),
    "resolve-uploaded-projects": lambda: RunnerManager.from_env().resolve_uploaded_projects(),
    "summarize-matrix-handshake": lambda: RunnerManager.from_env().summarize_matrix_handshake(),
    "preflight-trigger-queue": lambda: TriggerManager.from_env().preflight_queue(),
    "write-run-trigger": lambda: TriggerManager.from_env().write(),
    "force-clean-vm-restart": lambda: HandshakeManager.from_env().force_clean_vm_restart(),
    "handshake-timeout-diagnostics": lambda: HandshakeManager.from_env().timeout_diagnostics(),
    "post-pending-status": lambda: HandoffManager.from_env().post_pending_status(),
    "post-handoff-timeout-status": lambda: HandoffManager.from_env().post_handoff_timeout_status(),
    "cleanup-failed-trigger-artifacts": lambda: (
        HandoffManager.from_env().cleanup_failed_trigger_artifacts()
    ),
    "write-handoff-summary": lambda: HandoffManager.from_env().write_summary(),
    "stage-release-runner": lambda: PresetManager.from_env().stage_release_runner(),
    "compute-preset-info": lambda: PresetManager.from_env().compute_preset_info(),
}


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: bmt <command>\nCommands: {', '.join(sorted(COMMANDS))}", file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] in ("-h", "--help"):
        print(f"Usage: bmt <command>\nCommands: {', '.join(sorted(COMMANDS))}", file=sys.stderr)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Usage: bmt <command>\nCommands: {', '.join(sorted(COMMANDS))}", file=sys.stderr)
        sys.exit(1)
    COMMANDS[cmd]()


def _main_with(subcommand: str) -> None:
    sys.argv = ["bmt", subcommand] + sys.argv[1:]
    main()


def main_matrix() -> None:
    _main_with("matrix")


def main_write_run_trigger() -> None:
    _main_with("write-run-trigger")


def main_wait_handshake() -> None:
    _main_with("wait-handshake")


def main_start_vm() -> None:
    _main_with("start-vm")


def main_write_context() -> None:
    _main_with("write-context")


def main_write_handoff_summary() -> None:
    _main_with("write-handoff-summary")


def main_select_available_vm() -> None:
    _main_with("select-available-vm")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        gh_error(str(exc))
        sys.exit(1)

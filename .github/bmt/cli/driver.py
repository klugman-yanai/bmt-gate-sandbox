#!/usr/bin/env python3
"""BMT CI entrypoint. Each command reads its inputs from environment variables."""

from __future__ import annotations

import sys

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


class BmtRunner:
    """Facade for BMT subcommands. Each method delegates to the corresponding run_* in cli.commands."""

    def commands(self) -> list[str]:
        """Return subcommand names for usage/help."""
        return [
            "load-env",
            "matrix",
            "filter-supported-matrix",
            "parse-release-runners",
            "upload-runner",
            "select-available-vm",
            "start-vm",
            "sync-vm-metadata",
            "write-context",
            "wait-handshake",
            "resolve-failure-context",
            "filter-upload-matrix",
            "upload-runner-to-gcs",
            "resolve-uploaded-projects",
            "summarize-matrix-handshake",
            "preflight-trigger-queue",
            "write-run-trigger",
            "force-clean-vm-restart",
            "handshake-timeout-diagnostics",
            "post-pending-status",
            "post-handoff-timeout-status",
            "cleanup-failed-trigger-artifacts",
            "write-handoff-summary",
            "stage-release-runner",
            "compute-preset-info",
        ]

    def load_env(self) -> None:
        load_env.run_load_env()

    def matrix(self) -> None:
        matrix.run_build()

    def filter_supported_matrix(self) -> None:
        matrix.run_filter()

    def parse_release_runners(self) -> None:
        matrix.run_release_runners()

    def upload_runner(self) -> None:
        upload_runner.run()

    def select_available_vm(self) -> None:
        vm.run_select_available_vm()

    def start_vm(self) -> None:
        vm.run_start()

    def sync_vm_metadata(self) -> None:
        vm.run_sync_metadata()

    def write_context(self) -> None:
        workflow.run_write_context()

    def wait_handshake(self) -> None:
        workflow.run_wait_handshake()

    def resolve_failure_context(self) -> None:
        workflow.run_resolve_failure_context()

    def filter_upload_matrix(self) -> None:
        workflow.run_filter_upload_matrix()

    def upload_runner_to_gcs(self) -> None:
        workflow.run_upload_runner_to_gcs()

    def resolve_uploaded_projects(self) -> None:
        workflow.run_resolve_uploaded_projects()

    def summarize_matrix_handshake(self) -> None:
        workflow.run_summarize_matrix_handshake()

    def preflight_trigger_queue(self) -> None:
        workflow_trigger.run_preflight_trigger_queue()

    def write_run_trigger(self) -> None:
        trigger.run_trigger()

    def force_clean_vm_restart(self) -> None:
        workflow.run_force_clean_vm_restart()

    def handshake_timeout_diagnostics(self) -> None:
        workflow.run_handshake_timeout_diagnostics()

    def post_pending_status(self) -> None:
        workflow.run_post_pending_status()

    def post_handoff_timeout_status(self) -> None:
        workflow.run_post_handoff_timeout_status()

    def cleanup_failed_trigger_artifacts(self) -> None:
        workflow.run_cleanup_failed_trigger_artifacts()

    def write_handoff_summary(self) -> None:
        workflow.run_write_handoff_summary()

    def stage_release_runner(self) -> None:
        ci_workflow.run_stage_release_runner()

    def compute_preset_info(self) -> None:
        ci_workflow.run_compute_preset_info()


def main() -> None:
    runner = BmtRunner()
    if len(sys.argv) < 2:
        print(f"Usage: bmt <command>\nCommands: {', '.join(runner.commands())}", file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] in ("-h", "--help"):
        print(f"Usage: bmt <command>\nCommands: {', '.join(runner.commands())}", file=sys.stderr)
        sys.exit(0)
    cmd = sys.argv[1]
    method_name = cmd.replace("-", "_")
    if not hasattr(runner, method_name):
        print(f"Usage: bmt <command>\nCommands: {', '.join(runner.commands())}", file=sys.stderr)
        sys.exit(1)
    getattr(runner, method_name)()


def _main_with(subcommand: str) -> None:
    """Set argv to bmt <subcommand> + rest and run main(). Used by script shorthands (bmt-matrix, etc.)."""
    sys.argv = ["bmt", subcommand] + sys.argv[1:]
    main()


# Shorthand entry points for uv run bmt-<command> (see [project.scripts] in pyproject.toml).
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
        gh_output.gh_error(str(exc))
        sys.exit(1)

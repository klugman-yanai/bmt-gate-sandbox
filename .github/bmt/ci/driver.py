#!/usr/bin/env python3
"""BMT CI entrypoint."""

from __future__ import annotations

import sys
from collections.abc import Callable

from ci import config
from ci.actions import gh_error
from ci.handoff import HandoffManager
from ci.matrix import MatrixManager
from ci.preset import PresetManager
from ci.runner import RunnerManager
from ci.workflow_dispatch import WorkflowDispatchManager


def _load_env() -> None:
    config.load_env()


def _build_matrix() -> None:
    MatrixManager.from_env().build()


def _filter_supported_matrix() -> None:
    MatrixManager.from_env().filter_supported()


def _parse_release_runners() -> None:
    MatrixManager.from_env().parse_release_runners()


def _upload_runner() -> None:
    RunnerManager.from_env().upload()


def _write_context() -> None:
    HandoffManager.from_env().write_context()


def _resolve_failure_context() -> None:
    HandoffManager.from_env().resolve_failure_context()


def _filter_upload_matrix() -> None:
    RunnerManager.from_env().filter_upload_matrix()


def _upload_runner_to_gcs() -> None:
    RunnerManager.from_env().upload_runner_to_gcs()


def _validate_runner_in_repo() -> None:
    RunnerManager.from_env().validate_in_repo()


def _resolve_uploaded_projects() -> None:
    RunnerManager.from_env().resolve_uploaded_projects()


def _summarize_matrix_handshake() -> None:
    RunnerManager.from_env().summarize_matrix_handshake()


def _invoke_workflow() -> None:
    WorkflowDispatchManager.from_env().invoke()


def _post_pending_status() -> None:
    HandoffManager.from_env().post_pending_status()


def _post_handoff_timeout_status() -> None:
    HandoffManager.from_env().post_handoff_timeout_status()


def _validate_dataset_inputs() -> None:
    HandoffManager.from_env().validate_dataset_inputs()


def _write_handoff_summary() -> None:
    HandoffManager.from_env().write_summary()


def _stage_release_runner() -> None:
    PresetManager.from_env().stage_release_runner()


def _compute_preset_info() -> None:
    PresetManager.from_env().compute_preset_info()


def _commands() -> dict[str, Callable[[], None]]:
    return {
        "load-env": _load_env,
        "matrix": _build_matrix,
        "filter-supported-matrix": _filter_supported_matrix,
        "parse-release-runners": _parse_release_runners,
        "upload-runner": _upload_runner,
        "write-context": _write_context,
        "resolve-failure-context": _resolve_failure_context,
        "filter-upload-matrix": _filter_upload_matrix,
        "upload-runner-to-gcs": _upload_runner_to_gcs,
        "validate-runner-in-repo": _validate_runner_in_repo,
        "resolve-uploaded-projects": _resolve_uploaded_projects,
        "summarize-matrix-handshake": _summarize_matrix_handshake,
        "invoke-workflow": _invoke_workflow,
        "post-pending-status": _post_pending_status,
        "post-handoff-timeout-status": _post_handoff_timeout_status,
        "validate-dataset-inputs": _validate_dataset_inputs,
        "write-handoff-summary": _write_handoff_summary,
        "stage-release-runner": _stage_release_runner,
        "compute-preset-info": _compute_preset_info,
    }


def _usage(commands: dict[str, Callable[[], None]]) -> str:
    return f"Usage: bmt <command>\nCommands: {', '.join(sorted(commands))}"


def main() -> None:
    commands = _commands()
    if len(sys.argv) < 2:
        print(_usage(commands), file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] in ("-h", "--help"):
        print(_usage(commands), file=sys.stderr)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd not in commands:
        print(_usage(commands), file=sys.stderr)
        sys.exit(1)
    commands[cmd]()


def main_matrix() -> None:
    _build_matrix()


def main_write_context() -> None:
    _write_context()


def main_write_handoff_summary() -> None:
    _write_handoff_summary()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        gh_error(str(exc))
        sys.exit(1)

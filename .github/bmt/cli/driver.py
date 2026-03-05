#!/usr/bin/env python3
"""BMT CI entrypoint. Each command reads its inputs from environment variables."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `cli` package resolves when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from .commands import job, matrix, trigger, upload_runner, vm

COMMANDS = {
    "matrix": matrix.run_build,
    "filter-supported-matrix": matrix.run_filter,
    "parse-release-runners": matrix.run_release_runners,
    "trigger": trigger.run_trigger,
    "upload-runner": upload_runner.run,
    "start-vm": vm.run_start,
    "sync-vm-metadata": vm.run_sync_metadata,
    "wait-handshake": vm.run_wait_handshake,
    "execute-cloud-run-job": job.run_execute_cloud_run_job,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: driver.py <command>\nCommands: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)

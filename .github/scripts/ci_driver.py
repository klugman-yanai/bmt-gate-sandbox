#!/usr/bin/env python3
"""Thin CI entrypoint: matrix discovery, trigger, wait, and gate."""

from __future__ import annotations

import sys

import click

from ci.commands.job_matrix import command as matrix_cmd
from ci.commands.run_trigger import command as trigger_cmd
from ci.commands.start_vm import command as start_vm_cmd
from ci.commands.upload_runner import command as upload_runner_cmd
from ci.commands.verdict_gate import command as gate_cmd
from ci.commands.wait_handshake import command as wait_handshake_cmd
from ci.commands.wait_verdicts import command as wait_cmd


@click.group()
def cli() -> None:
    pass


cli.add_command(matrix_cmd)
cli.add_command(trigger_cmd)
cli.add_command(start_vm_cmd)
cli.add_command(upload_runner_cmd)
cli.add_command(wait_handshake_cmd)
cli.add_command(wait_cmd)
cli.add_command(gate_cmd)

if __name__ == "__main__":
    try:
        cli()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)

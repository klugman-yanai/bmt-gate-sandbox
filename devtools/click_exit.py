#!/usr/bin/env python3
"""Helpers for consistent Click CLI exit-code behavior."""

from __future__ import annotations

from typing import Any

import click


def run_click_command(command: click.Command) -> int:
    """Run a Click command and propagate callback return values as process exit codes."""
    try:
        result: Any = command.main(standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return int(exc.exit_code)
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1

    if result is None:
        return 0
    if isinstance(result, bool):
        return int(result)
    if isinstance(result, int):
        return result
    return 0

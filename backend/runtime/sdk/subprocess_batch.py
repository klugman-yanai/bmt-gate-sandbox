"""Subprocess helpers for batch-style commands from plugins (workspace cwd, timeout, logging)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path


def run_subprocess_in_workspace(
    command: list[str],
    *,
    cwd: Path,
    timeout_sec: float,
    log: logging.Logger,
    label: str = "batch",
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` with ``cwd``, bounded by ``timeout_sec``; capture stdout/stderr as text.

    Does not raise on non-zero exit; callers inspect ``returncode``. Logs a warning on timeout.
    """
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        log.warning("%s subprocess timed out after %s s; command=%s", label, timeout_sec, command)
        raise

"""Whether external CLIs are on PATH (single implementation; prefer over `subprocess` + `which`)."""

from __future__ import annotations

import shutil


def command_available(name: str) -> bool:
    """Return True if `name` resolves on PATH (same semantics as POSIX `command -v`)."""
    return shutil.which(name) is not None

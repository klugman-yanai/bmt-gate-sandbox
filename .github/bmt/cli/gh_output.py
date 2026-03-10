"""GitHub Actions workflow command output. Use these so GHA parses annotations and groups correctly."""

from __future__ import annotations

import sys


def _escape(s: str) -> str:
    """Escape newlines so GHA parses the annotation as a single line."""
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def gh_error(message: str) -> None:
    """Emit a GHA error annotation (visible in Actions UI)."""
    print(f"::error::{_escape(message)}", file=sys.stderr, flush=True)


def gh_warning(message: str) -> None:
    """Emit a GHA warning annotation."""
    print(f"::warning::{_escape(message)}", file=sys.stderr, flush=True)


def gh_notice(message: str) -> None:
    """Emit a GHA notice annotation."""
    print(f"::notice::{_escape(message)}", file=sys.stderr, flush=True)


def gh_debug(message: str) -> None:
    """Emit a GHA debug message (shown when step debug logging is enabled)."""
    print(f"::debug::{_escape(message)}", file=sys.stderr, flush=True)


def gh_group(title: str) -> None:
    """Start a collapsible group in the job log."""
    print(f"::group::{_escape(title)}", flush=True)


def gh_endgroup() -> None:
    """End the current collapsible group."""
    print("::endgroup::", flush=True)

"""Shared time helpers: UTC wall-clock only.

Use datetime.now(timezone.utc) for timestamps; use time.monotonic() for durations.
See CLAUDE.md § Time and clocks.
"""

from __future__ import annotations

from whenever import Instant


def now_iso() -> str:
    """Current time in UTC as ISO-like string (e.g. 2026-02-19T12:00:00Z)."""
    return Instant.now().format_iso()


def now_stamp() -> str:
    """Current time in UTC as compact stamp (e.g. 20260219T120000Z)."""
    return Instant.now().format_iso(unit="second", basic=True)

"""Shared time helpers: UTC wall-clock only.

Use datetime.now(timezone.utc) for timestamps; use time.monotonic() for durations.
See CLAUDE.md § Time and clocks.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Current time in UTC as ISO-like string (e.g. 2026-02-19T12:00:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_stamp() -> str:
    """Current time in UTC as compact stamp (e.g. 20260219T120000Z)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_epoch() -> float:
    """Current time in UTC as seconds since epoch (for TTL/cutoff comparisons)."""
    return datetime.now(timezone.utc).timestamp()

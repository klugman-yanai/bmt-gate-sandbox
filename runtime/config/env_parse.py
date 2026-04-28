"""Parsing helpers for environment-shaped strings (no I/O)."""

from __future__ import annotations

import os

__all__ = ["force_pass_dispatch_requested", "is_truthy_env_value"]

_TRUTHY_TOKENS = frozenset({"1", "true", "yes"})


def is_truthy_env_value(value: str | None) -> bool:
    """True if *value* is a common env-flag string: 1, true, or yes (case-insensitive, stripped)."""
    return (value or "").strip().lower() in _TRUTHY_TOKENS


def force_pass_dispatch_requested() -> bool:
    """True when handoff asked for force-pass dispatch (Cloud Run still runs full BMT; see runtime docs)."""
    return is_truthy_env_value(os.environ.get("BMT_FORCE_PASS")) or is_truthy_env_value(
        os.environ.get("KARDOME_BMT_FORCE_PASS")
    )

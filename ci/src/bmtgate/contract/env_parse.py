"""Parsing helpers for environment-shaped strings (no I/O)."""

from __future__ import annotations

__all__ = ["is_truthy_env_value"]

_TRUTHY_TOKENS = frozenset({"1", "true", "yes"})


def is_truthy_env_value(value: str | None) -> bool:
    """True if *value* is a common env-flag string: 1, true, or yes (case-insensitive, stripped)."""
    return (value or "").strip().lower() in _TRUTHY_TOKENS

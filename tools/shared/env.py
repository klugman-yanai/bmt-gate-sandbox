"""Centralized environment variable access.

Use get(), require(), get_bool() for one-off env reads. For structured config
(e.g. CI/GCP) the codebase uses pydantic-settings BaseSettings (e.g. BmtConfig
in .github/bmt/ci/config.py), which loads from env and optional .env.
"""

from __future__ import annotations

import os

_TRUTHY_VALUES = frozenset({"1", "true", "yes"})


def get(key: str, default: str = "") -> str:
    """Return env var value, stripped; use default if missing or empty."""
    return (os.getenv(key) or default).strip()


def get_bool(key: str) -> bool:
    """Return True if env var is truthy (1, true, yes), case-insensitive."""
    return (os.getenv(key) or "").strip().lower() in _TRUTHY_VALUES


def require(key: str) -> str:
    """Return env var value, stripped; raise RuntimeError if missing or empty."""
    value = get(key)
    if not value:
        raise RuntimeError(f"Required env var {key!r} is not set or empty")
    return value


def environ_dict() -> dict[str, str]:
    """Return current process environment as a dict (e.g. for passing to config loaders)."""
    return dict(os.environ)

"""Value types and sanitization for pipeline identifiers (no I/O)."""

from __future__ import annotations

import re

__all__ = ["sanitize_run_id"]

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")

RUN_ID_MAX_LEN = 200


def sanitize_run_id(raw: str) -> str:
    """Normalize workflow/run id for GCS object paths (matches CI trigger path contract)."""
    value = _RUN_ID_SAFE.sub("-", (raw or "").strip())
    value = value.strip("-._")
    if not value:
        raise ValueError("run_id is empty after sanitization")
    return value[:RUN_ID_MAX_LEN]

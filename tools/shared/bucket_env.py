"""Shared bucket/env helpers for tools scripts.

Scripts organized by prefix:
- shared_* — shared libraries (not executed directly)
- bucket_* — GCS bucket operations
- bmt_* — BMT execution and monitoring
- gh_* — GitHub/debug utilities
"""

from __future__ import annotations

import os


def get_bucket_from_env() -> str:
    """Bucket name from canonical GCS_BUCKET env var."""
    return (os.environ.get("GCS_BUCKET") or "").strip()


def bucket_from_env() -> str:
    """Bucket for script entrypoints: GCS_BUCKET env var."""
    return get_bucket_from_env()


def truthy(val: str | None) -> bool:
    """True if value is a truthy env-like string (1, true, yes)."""
    return (val or "").strip().lower() in ("1", "true", "yes")


def code_bucket_root_uri(bucket: str) -> str:
    """Code bucket root: gs://<bucket>/code."""
    return f"gs://{bucket}/code"


def runtime_bucket_root_uri(bucket: str) -> str:
    """Runtime bucket root: gs://<bucket>/runtime."""
    return f"gs://{bucket}/runtime"

"""Shared bucket/env helpers for devtools scripts."""

from __future__ import annotations

import os


def get_bucket_from_env() -> str:
    """Bucket name from BUCKET or GCS_BUCKET (empty if unset)."""
    return os.environ.get("BUCKET") or os.environ.get("GCS_BUCKET", "")


def bucket_root_uri(bucket: str, prefix: str) -> str:
    """gs://bucket or gs://bucket/prefix with leading/trailing slashes normalized."""
    p = (prefix or "").strip("/")
    return f"gs://{bucket}/{p}" if p else f"gs://{bucket}"

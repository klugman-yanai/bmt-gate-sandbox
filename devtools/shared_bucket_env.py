"""Shared bucket/env helpers for devtools scripts.

Scripts organized by prefix:
- shared_* — shared libraries (not executed directly)
- bucket_* — GCS bucket operations
- bmt_* — BMT execution and monitoring
- gh_* — GitHub/debug utilities
"""

from __future__ import annotations

import os

import click


def get_bucket_from_env() -> str:
    """Bucket name from BUCKET or GCS_BUCKET (empty if unset)."""
    return os.environ.get("BUCKET") or os.environ.get("GCS_BUCKET", "")


def bucket_root_uri(bucket: str, prefix: str) -> str:
    """gs://bucket or gs://bucket/prefix with leading/trailing slashes normalized."""
    p = (prefix or "").strip("/")
    return f"gs://{bucket}/{p}" if p else f"gs://{bucket}"


bucket_option = click.option(
    "--bucket",
    default=get_bucket_from_env(),
    help="GCS bucket name (default: BUCKET or GCS_BUCKET env)",
)
bucket_prefix_option = click.option(
    "--bucket-prefix",
    default=os.environ.get("BMT_BUCKET_PREFIX", ""),
    help="Optional prefix path within bucket",
)

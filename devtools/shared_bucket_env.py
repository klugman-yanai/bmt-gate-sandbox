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
    """Bucket name from canonical GCS_BUCKET env var."""
    return (os.environ.get("GCS_BUCKET") or "").strip()


def get_bucket_prefix_from_env() -> str:
    """Optional bucket prefix from canonical BMT_BUCKET_PREFIX env var."""
    return (os.environ.get("BMT_BUCKET_PREFIX") or "").strip()


def bucket_root_uri(bucket: str, prefix: str) -> str:
    """gs://bucket or gs://bucket/prefix with leading/trailing slashes normalized."""
    p = (prefix or "").strip("/")
    return f"gs://{bucket}/{p}" if p else f"gs://{bucket}"


bucket_option = click.option(
    "--bucket",
    default=get_bucket_from_env,
    callback=lambda _ctx, _param, value: value or get_bucket_from_env(),
    help="GCS bucket name (default: GCS_BUCKET env)",
)
bucket_prefix_option = click.option(
    "--bucket-prefix",
    default=get_bucket_prefix_from_env,
    help="Optional prefix path within bucket",
)

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


def code_bucket_root_uri(bucket: str) -> str:
    """Code bucket root: gs://<bucket>/code."""
    return f"gs://{bucket}/code"


def runtime_bucket_root_uri(bucket: str) -> str:
    """Runtime bucket root: gs://<bucket>/runtime."""
    return f"gs://{bucket}/runtime"


bucket_option = click.option(
    "--bucket",
    default=get_bucket_from_env,
    callback=lambda _ctx, _param, value: value or get_bucket_from_env(),
    help="GCS bucket name (default: GCS_BUCKET env)",
)

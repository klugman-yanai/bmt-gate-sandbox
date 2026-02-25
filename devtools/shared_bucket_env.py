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


def normalize_prefix(prefix: str) -> str:
    """Canonical slash-normalized prefix."""
    return (prefix or "").strip("/")


def parent_prefix(prefix: str) -> str:
    """Canonical parent namespace from BMT_BUCKET_PREFIX."""
    return normalize_prefix(prefix)


def child_prefix(parent: str, leaf: str) -> str:
    """Join parent and leaf namespace."""
    parent_norm = parent_prefix(parent)
    leaf_norm = normalize_prefix(leaf)
    if not leaf_norm:
        return parent_norm
    return f"{parent_norm}/{leaf_norm}" if parent_norm else leaf_norm


def code_prefix(parent: str) -> str:
    """Derived code namespace."""
    return child_prefix(parent, "code")


def runtime_prefix(parent: str) -> str:
    """Derived runtime namespace."""
    return child_prefix(parent, "runtime")


def code_bucket_root_uri(bucket: str, parent: str) -> str:
    """Code bucket root URI under parent prefix."""
    return bucket_root_uri(bucket, code_prefix(parent))


def runtime_bucket_root_uri(bucket: str, parent: str) -> str:
    """Runtime bucket root URI under parent prefix."""
    return bucket_root_uri(bucket, runtime_prefix(parent))


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

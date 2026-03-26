"""Shared bucket/env helpers for tools scripts.

Scripts organized by prefix:
- shared_* — shared libraries (not executed directly)
- bucket_* — GCS bucket operations
- bmt_* — BMT execution and monitoring
- gh_* — GitHub/debug utilities
"""

from __future__ import annotations

from backend.config.constants import ENV_GCS_BUCKET
from backend.config.env_parse import is_truthy_env_value
from tools.shared.repo_vars import repo_var


def get_bucket_from_env() -> str:
    """Bucket name from env first, then GitHub repo vars."""
    return repo_var(ENV_GCS_BUCKET)


def bucket_from_env() -> str:
    """Bucket for script entrypoints: GCS_BUCKET env var."""
    return get_bucket_from_env()


def truthy(val: str | None) -> bool:
    """True if value is a truthy env-like string (1, true, yes)."""
    return is_truthy_env_value(val)


def bucket_root_uri(bucket: str) -> str:
    """Bucket root: gs://<bucket>.

    The bucket is a 1:1 mirror of gcp/stage/. All runtime data
    (triggers, runners, datasets, results) lives directly under this root.
    """
    return f"gs://{bucket}"


def runtime_bucket_root_uri(bucket: str) -> str:
    """Bucket root (alias): gs://<bucket>.

    The bucket is a 1:1 mirror of gcp/stage/; there is no runtime/ prefix.
    """
    return bucket_root_uri(bucket)

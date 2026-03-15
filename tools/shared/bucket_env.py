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


def bucket_root_uri(bucket: str) -> str:
    """Bucket root: gs://<bucket>. No code/ or runtime/ prefix.

    Use this for runtime/, _meta/, and other non-code namespaces.
    For the code namespace (gcp/image → VM) use code_bucket_root_uri.
    """
    return f"gs://{bucket}"


def code_bucket_root_uri(bucket: str) -> str:
    """Code namespace root: gs://<bucket>/code.

    This is where gcp/image is synced to and where the VM startup
    script downloads from (gcloud storage rsync gs://<bucket>/code /opt/bmt).
    """
    return f"gs://{bucket}/code"


def runtime_bucket_root_uri(bucket: str) -> str:
    """Runtime namespace root: gs://<bucket>/runtime.

    This is where gcp/remote (runners, datasets, triggers, results) lives.
    """
    return f"gs://{bucket}/runtime"

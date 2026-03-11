"""Shared utility functions for BMT GCP code."""

from __future__ import annotations

from whenever import Instant


def _now_iso() -> str:
    return Instant.now().format_iso(unit="second")


def _now_stamp() -> str:
    return Instant.now().format_iso(unit="second", basic=True)


def _code_bucket_root(bucket: str) -> str:
    return f"gs://{bucket}/code"


def _runtime_bucket_root(bucket: str) -> str:
    return f"gs://{bucket}/runtime"


def _bucket_uri(bucket_root: str, path_or_uri: str) -> str:
    if path_or_uri.startswith("gs://"):
        return path_or_uri
    return f"{bucket_root}/{path_or_uri.lstrip('/')}"


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse 'gs://bucket/path/to/blob' → ('bucket', 'path/to/blob')."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a GCS URI: {uri!r}")
    parts = uri[len("gs://") :].split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")

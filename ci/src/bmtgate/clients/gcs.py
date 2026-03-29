"""GCS operations using google-cloud-storage. One client per process."""

from __future__ import annotations

import functools
import json
import re
from typing import Any

from google.api_core import exceptions as api_exceptions
from google.auth import exceptions as google_auth_exceptions
from google.cloud import storage

# gs://bucket-name/path/to/object
_GS_URI = re.compile(r"^gs://([^/]+)/(.*)$")


class GcsError(RuntimeError):
    """Raised when a GCS operation fails in a non-recoverable way."""


_GCS_OPERATION_ERRORS: tuple[type[BaseException], ...] = (
    api_exceptions.GoogleAPIError,
    google_auth_exceptions.GoogleAuthError,
    OSError,
    TypeError,
)


@functools.lru_cache(maxsize=1)
def _client_singleton() -> storage.Client:
    """Single client per process (uses default credentials, e.g. WIF in Actions)."""
    return storage.Client()


def _get_client() -> storage.Client:
    """Return the process-wide GCS client."""
    return _client_singleton()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Parse gs://bucket/path to (bucket_name, blob_path). Raises ValueError if invalid."""
    m = _GS_URI.match(uri.strip())
    if not m:
        raise ValueError(f"Invalid GCS URI: {uri!r}")
    bucket_name, path = m.group(1), m.group(2)
    if not bucket_name:
        raise ValueError(f"Invalid GCS URI (empty bucket): {uri!r}")
    return bucket_name, path.strip("/") or ""


def read_object(uri: str) -> bytes:
    """Download a GCS object as raw bytes. Raises GcsError on failure."""
    try:
        bucket_name, path = parse_gs_uri(uri)
        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        return blob.download_as_bytes()
    except ValueError as exc:
        raise GcsError(str(exc)) from exc
    except _GCS_OPERATION_ERRORS as exc:
        raise GcsError(f"Failed to read {uri}: {exc}") from exc


def write_object(uri: str, data: bytes | str) -> None:
    """Upload raw bytes or str to GCS. Raises GcsError on failure."""
    try:
        bucket_name, path = parse_gs_uri(uri)
        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        if isinstance(data, str):
            data = data.encode("utf-8")
        blob.upload_from_string(data)
    except ValueError as exc:
        raise GcsError(str(exc)) from exc
    except _GCS_OPERATION_ERRORS as exc:
        raise GcsError(f"Failed to write {uri}: {exc}") from exc


def list_prefix(prefix_uri: str) -> list[str]:
    """List blob names under gs://bucket/prefix (returns full gs:// URIs)."""
    try:
        bucket_name, prefix_path = parse_gs_uri(prefix_uri)
        client = _get_client()
        bucket = client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix_path)
        out: list[str] = []
        for b in blobs:
            if b.name:
                out.append(f"gs://{bucket_name}/{b.name}")
        return out
    except ValueError as exc:
        raise GcsError(str(exc)) from exc
    except _GCS_OPERATION_ERRORS as exc:
        raise GcsError(f"Failed to list {prefix_uri}: {exc}") from exc


def delete_object(uri: str) -> None:
    """Delete a GCS object. Raises GcsError on failure (not on 404)."""
    try:
        bucket_name, path = parse_gs_uri(uri)
        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        blob.delete()
    except ValueError as exc:
        raise GcsError(str(exc)) from exc
    except api_exceptions.NotFound:
        return  # already deleted; treat as success
    except _GCS_OPERATION_ERRORS as exc:
        raise GcsError(f"Failed to delete {uri}: {exc}") from exc


def object_exists(uri: str) -> bool:
    """Return True if the GCS object exists.

    Raises :exc:`ValueError` for invalid ``gs://`` URIs. Propagates :exc:`GcsError` on
    GCS/network/auth failures so callers do not treat infrastructure errors as "missing".
    """
    try:
        bucket_name, path = parse_gs_uri(uri)
        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        return blob.exists()
    except ValueError:
        raise
    except _GCS_OPERATION_ERRORS as exc:
        raise GcsError(f"Failed to check existence of {uri}: {exc}") from exc


def upload_json(uri: str, payload: dict[str, Any]) -> None:
    """Upload a JSON object to GCS. Raises GcsError on failure."""
    data = json.dumps(payload, indent=2) + "\n"
    write_object(uri, data)


def create_json_if_absent(uri: str, payload: dict[str, Any]) -> bool:
    """Create a JSON object only when it does not already exist."""
    try:
        bucket_name, path = parse_gs_uri(uri)
        blob = _get_client().bucket(bucket_name).blob(path)
        blob.upload_from_string(json.dumps(payload, indent=2) + "\n", if_generation_match=0)
        return True
    except ValueError as exc:
        raise GcsError(str(exc)) from exc
    except api_exceptions.PreconditionFailed:
        return False
    except _GCS_OPERATION_ERRORS as exc:
        raise GcsError(f"Failed to create {uri}: {exc}") from exc


def download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a GCS object as JSON; return (payload, None) or (None, error_message)."""
    try:
        raw = read_object(uri)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return None, "invalid_json: expected object"
        return payload, None
    except GcsError as exc:
        return None, str(exc)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc}"

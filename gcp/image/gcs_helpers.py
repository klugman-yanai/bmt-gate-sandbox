"""GCS client and low-level operations for vm_watcher. Leaf module (no gcp.image vm_watcher deps)."""

from __future__ import annotations

import json
import traceback
from datetime import timedelta
from typing import Any

from google.api_core import exceptions as gcs_exceptions
from google.cloud import storage as gcs_lib

# Default expiry for log-dump signed URLs (must match GCS lifecycle retention on log-dumps/)
LOG_DUMP_SIGNED_URL_EXPIRY_DAYS: int = 3

_gcs_client_holder: list[gcs_lib.Client | None] = [None]


def _get_gcs_client() -> gcs_lib.Client:
    if _gcs_client_holder[0] is None:
        _gcs_client_holder[0] = gcs_lib.Client()
    return _gcs_client_holder[0]


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse 'gs://bucket/path/to/blob' → ('bucket', 'path/to/blob')."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a GCS URI: {uri}")
    parts = uri[5:].split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _gcs_list(uri: str) -> list[str]:
    """List all objects under a GCS URI prefix. Returns full gs:// URIs."""
    bucket_name, prefix = _parse_gcs_uri(uri)
    try:
        blobs = _get_gcs_client().list_blobs(bucket_name, prefix=prefix)
        return [f"gs://{bucket_name}/{b.name}" for b in blobs]
    except (gcs_exceptions.GoogleAPICallError, OSError):
        return []


def _gcloud_ls(uri: str, *, recursive: bool = False) -> list[str]:  # noqa: ARG001 (recursive ignored)
    """List objects under a GCS URI prefix. Returns list of full URIs."""
    return _gcs_list(uri)


def _gcloud_download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a JSON object from GCS.

    Returns:
      (payload, None) on success.
      (None, "download_failed") on 404 or transient download failures.
      (None, "invalid_json") when object exists but payload is malformed.
    """
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
        text = blob.download_as_text(encoding="utf-8")
    except gcs_exceptions.NotFound:
        return None, "download_failed"
    except (gcs_exceptions.GoogleAPICallError, OSError):
        traceback.print_exc()
        raise
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_json"
    return payload, None


def _gcloud_upload_json(uri: str, payload: dict[str, Any]) -> bool:
    """Upload a JSON object to GCS. Returns True on success."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
        blob.upload_from_string(
            json.dumps(payload, indent=2) + "\n",
            content_type="application/json",
        )
        return True
    except (gcs_exceptions.GoogleAPICallError, OSError):
        traceback.print_exc()
        return False


def _gcloud_upload_text(uri: str, content: str, content_type: str = "text/plain; charset=utf-8") -> bool:
    """Upload raw text to a GCS object (e.g. log dumps). Returns True on success."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        blob = _get_gcs_client().bucket(bucket_name).blob(blob_name)
        blob.upload_from_string(content, content_type=content_type)
        return True
    except (gcs_exceptions.GoogleAPICallError, OSError):
        traceback.print_exc()
        return False


def generate_signed_url(
    bucket_name: str,
    object_name: str,
    expiration: timedelta | None = None,
) -> str | None:
    """Generate a GET signed URL for a GCS object (V4). Returns None if signing fails.

    VM needs credentials that can sign (e.g. service account key or iam.serviceAccounts.signBlob).
    """
    if expiration is None:
        expiration = timedelta(days=LOG_DUMP_SIGNED_URL_EXPIRY_DAYS)
    try:
        blob = _get_gcs_client().bucket(bucket_name).blob(object_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=expiration,
            method="GET",
        )
    except (gcs_exceptions.GoogleAPICallError, OSError, ValueError):
        traceback.print_exc()
        return None


def _gcloud_rm(uri: str, *, recursive: bool = False) -> bool:
    """Delete a GCS object or all objects under a prefix."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    client = _get_gcs_client()
    try:
        if recursive:
            blobs = list(client.list_blobs(bucket_name, prefix=blob_name))
            if blobs:
                with client.batch():
                    for blob in blobs:
                        blob.delete()
        else:
            client.bucket(bucket_name).blob(blob_name).delete()
        return True
    except gcs_exceptions.NotFound:
        return True  # already gone
    except (gcs_exceptions.GoogleAPICallError, OSError):
        return False


def _gcloud_exists(uri: str) -> bool:
    """Return True when a GCS object exists."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        return _get_gcs_client().bucket(bucket_name).blob(blob_name).exists()
    except (gcs_exceptions.GoogleAPICallError, OSError):
        return False

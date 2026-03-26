"""Helper functions for reading/writing VM execution status to GCS."""

from __future__ import annotations

import json
import threading
from typing import Any

from google.api_core import exceptions as api_exceptions
from google.cloud import storage
from whenever import Instant

_TERMINAL_RUN_OUTCOMES = {"completed", "cancelled", "skipped", "failed", "error"}
_status_lock = threading.Lock()

_gcs_client: storage.Client | None = None


def _get_client() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


def _now_iso() -> str:
    return Instant.now().format_iso(unit="second")


def _normalize_prefix(prefix: str) -> str:
    return (prefix or "").strip("/")


def _bucket_root(bucket: str, runtime_prefix: str) -> str:
    clean = _normalize_prefix(runtime_prefix)
    return f"gs://{bucket}/{clean}" if clean else f"gs://{bucket}"


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a GCS URI: {uri!r}")
    parts = uri[len("gs://"):].split("/", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def status_uri(bucket: str, runtime_prefix: str, run_id: str) -> str:
    """Build GCS URI for one workflow status file."""
    return f"{_bucket_root(bucket, runtime_prefix)}/triggers/status/{run_id}.json"


def _last_run_meta_uri(bucket: str, runtime_prefix: str) -> str:
    """Build GCS URI for last-run metadata (duration for ETA)."""
    return f"{_bucket_root(bucket, runtime_prefix)}/triggers/last_run_meta.json"


def _upload_json(uri: str, payload: dict[str, Any]) -> None:
    """Upload JSON payload to GCS. Raises RuntimeError on failure."""
    bucket_name, blob_name = _parse_gcs_uri(uri)
    data = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    try:
        _get_client().bucket(bucket_name).blob(blob_name).upload_from_string(
            data, content_type="application/json"
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to upload {uri}: {exc}") from exc


def _download_json(uri: str) -> dict[str, Any] | None:
    """Download and parse a JSON object from GCS.

    Returns the payload dict, or None if the object does not exist (404).
    Raises RuntimeError for unexpected errors (auth, network, malformed JSON).
    """
    bucket_name, blob_name = _parse_gcs_uri(uri)
    try:
        text = _get_client().bucket(bucket_name).blob(blob_name).download_as_text(encoding="utf-8")
    except api_exceptions.NotFound:
        return None
    except Exception as exc:
        raise RuntimeError(f"Failed to download {uri}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Malformed JSON at {uri}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"Unexpected JSON type at {uri}: expected object, got {type(payload).__name__}")
    return payload


def write_last_run_duration(bucket: str, runtime_prefix: str, duration_sec: int) -> None:
    """Persist last run duration so the next run can show ETA in the Check Run."""
    uri = _last_run_meta_uri(bucket, runtime_prefix)
    _upload_json(uri, {"last_run_duration_sec": duration_sec, "updated_at": _now_iso()})


def read_last_run_duration(bucket: str, runtime_prefix: str) -> int | None:
    """Read last run duration (seconds) for ETA; None if not available."""
    uri = _last_run_meta_uri(bucket, runtime_prefix)
    try:
        payload = _download_json(uri)
    except RuntimeError:
        return None  # ETA is optional; suppress errors to avoid blocking the run
    if payload is None:
        return None
    val = payload.get("last_run_duration_sec")
    if isinstance(val, int) and val >= 0:
        return val
    if isinstance(val, float) and val >= 0:
        return int(val)
    return None


def _is_terminal_status(status: dict[str, Any]) -> bool:
    run_outcome_raw = status.get("run_outcome")
    if not isinstance(run_outcome_raw, str):
        return False
    run_outcome = run_outcome_raw.strip().lower()
    return run_outcome in _TERMINAL_RUN_OUTCOMES


def write_status(bucket: str, runtime_prefix: str, run_id: str, status: dict[str, Any]) -> None:
    """Atomically write status file to GCS."""
    _upload_json(status_uri(bucket, runtime_prefix, run_id), status)


def read_status(bucket: str, runtime_prefix: str, run_id: str) -> dict[str, Any] | None:
    """Read current status file from GCS.

    Returns the status dict, or None if not found (404).
    Raises RuntimeError for unexpected errors (auth, network, malformed JSON).
    """
    return _download_json(status_uri(bucket, runtime_prefix, run_id))


def update_heartbeat(bucket: str, runtime_prefix: str, run_id: str) -> None:
    """Update heartbeat timestamp for a run status object."""
    with _status_lock:
        status = read_status(bucket, runtime_prefix, run_id)
        if status is None:
            return
        if _is_terminal_status(status):
            return
        status["last_heartbeat"] = _now_iso()
        write_status(bucket, runtime_prefix, run_id, status)


def update_leg_progress(
    bucket: str,
    runtime_prefix: str,
    run_id: str,
    leg_index: int,
    files_completed: int,
    files_total: int,
) -> None:
    """Update per-leg file progress and heartbeat."""
    with _status_lock:
        status = read_status(bucket, runtime_prefix, run_id)
        if status is None:
            return
        if _is_terminal_status(status):
            return
        legs = status.get("legs")
        if not isinstance(legs, list):
            return
        if 0 <= leg_index < len(legs) and isinstance(legs[leg_index], dict):
            leg = legs[leg_index]
            leg["files_completed"] = files_completed
            leg["files_total"] = files_total
            current_leg = status.get("current_leg")
            if isinstance(current_leg, dict) and current_leg.get("index") == leg_index:
                current_leg["files_completed"] = files_completed
                current_leg["files_total"] = files_total
        status["last_heartbeat"] = _now_iso()
        write_status(bucket, runtime_prefix, run_id, status)

"""Helper functions for reading/writing VM execution status to GCS."""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TERMINAL_RUN_OUTCOMES = {"completed", "cancelled", "skipped", "failed", "error"}
_status_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_prefix(prefix: str) -> str:
    return (prefix or "").strip("/")


def _bucket_root(bucket: str, runtime_prefix: str) -> str:
    clean = _normalize_prefix(runtime_prefix)
    return f"gs://{bucket}/{clean}" if clean else f"gs://{bucket}"


def status_uri(bucket: str, runtime_prefix: str, run_id: str) -> str:
    """Build GCS URI for one workflow status file."""
    return f"{_bucket_root(bucket, runtime_prefix)}/triggers/status/{run_id}.json"


def _last_run_meta_uri(bucket: str, runtime_prefix: str) -> str:
    """Build GCS URI for last-run metadata (duration for ETA)."""
    return f"{_bucket_root(bucket, runtime_prefix)}/triggers/last_run_meta.json"


def write_last_run_duration(bucket: str, runtime_prefix: str, duration_sec: int) -> None:
    """Persist last run duration so the next run can show ETA in the Check Run."""
    gcs_path = _last_run_meta_uri(bucket, runtime_prefix)
    payload = {"last_run_duration_sec": duration_sec, "updated_at": _now_iso()}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, indent=2)
        temp_path = Path(handle.name)
    try:
        subprocess.run(
            ["gcloud", "storage", "cp", str(temp_path), gcs_path, "--quiet"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def read_last_run_duration(bucket: str, runtime_prefix: str) -> int | None:
    """Read last run duration (seconds) for ETA; None if not available."""
    gcs_path = _last_run_meta_uri(bucket, runtime_prefix)
    try:
        result = subprocess.run(
            ["gcloud", "storage", "cat", gcs_path],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
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
    gcs_path = status_uri(bucket, runtime_prefix, run_id)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
        json.dump(status, handle, indent=2)
        temp_path = Path(handle.name)
    try:
        subprocess.run(
            ["gcloud", "storage", "cp", str(temp_path), gcs_path, "--quiet"],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def read_status(bucket: str, runtime_prefix: str, run_id: str) -> dict[str, Any] | None:
    """Read current status file from GCS."""
    gcs_path = status_uri(bucket, runtime_prefix, run_id)
    try:
        result = subprocess.run(
            ["gcloud", "storage", "cat", gcs_path],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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

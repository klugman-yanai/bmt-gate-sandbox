"""Helper functions for reading/writing VM execution status to GCS.

The status file provides live progress tracking during BMT execution:
- Heartbeat updates (VM is alive)
- Leg-level progress (which leg is running)
- File-level progress (files completed in current leg)
- ETA estimation based on historical timing
"""

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _gcs_path(bucket: str, run_id: str) -> str:
    """Build GCS path for status file."""
    return f"gs://{bucket}/triggers/status/{run_id}.json"


def write_status(bucket: str, run_id: str, status: dict[str, Any]) -> None:
    """Atomically write status file to GCS.

    Args:
        bucket: GCS bucket name
        run_id: Workflow run ID (unique identifier for this execution)
        status: Status dict to write

    Raises:
        subprocess.CalledProcessError: If gcloud upload fails
    """
    gcs_path = _gcs_path(bucket, run_id)

    # Write to temp file, then upload
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(status, f, indent=2)
        temp_path = Path(f.name)

    try:
        subprocess.run(
            ["gcloud", "storage", "cp", str(temp_path), gcs_path],
            check=True,
            capture_output=True,
            text=True
        )
    finally:
        temp_path.unlink()


def read_status(bucket: str, run_id: str) -> dict[str, Any] | None:
    """Read current status file from GCS.

    Args:
        bucket: GCS bucket name
        run_id: Workflow run ID

    Returns:
        Status dict if file exists, None otherwise
    """
    gcs_path = _gcs_path(bucket, run_id)

    try:
        result = subprocess.run(
            ["gcloud", "storage", "cat", gcs_path],
            check=True,
            capture_output=True,
            text=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError:
        return None


def update_heartbeat(bucket: str, run_id: str) -> None:
    """Update only the heartbeat timestamp.

    This is called periodically by a background thread to prove VM is alive.

    Args:
        bucket: GCS bucket name
        run_id: Workflow run ID
    """
    status = read_status(bucket, run_id)
    if status is None:
        return  # Status file doesn't exist yet, skip

    status["last_heartbeat"] = _now_iso()
    write_status(bucket, run_id, status)


def update_leg_progress(
    bucket: str,
    run_id: str,
    leg_index: int,
    files_completed: int,
    files_total: int
) -> None:
    """Update progress for a specific leg.

    Called by manager during execution to show file-level progress.

    Args:
        bucket: GCS bucket name
        run_id: Workflow run ID
        leg_index: Index of the leg being executed (0-based)
        files_completed: Number of files processed so far
        files_total: Total number of files for this leg
    """
    status = read_status(bucket, run_id)
    if status is None:
        return  # Status file doesn't exist, skip

    # Update the specific leg
    if leg_index < len(status["legs"]):
        status["legs"][leg_index]["files_completed"] = files_completed
        status["legs"][leg_index]["files_total"] = files_total

        # Update current_leg if this is the active one
        if status.get("current_leg") and status["current_leg"]["index"] == leg_index:
            status["current_leg"]["files_completed"] = files_completed
            status["current_leg"]["files_total"] = files_total

    status["last_heartbeat"] = _now_iso()
    write_status(bucket, run_id, status)

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


class GcloudError(RuntimeError):
    """Raised when a gcloud command fails in a non-recoverable way."""


def run_capture(cmd: list[str]) -> tuple[int, str]:
    """Run command; return (exit_code, stderr or stdout)."""
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    text = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode, text


def run_capture_retry(
    cmd: list[str],
    attempts: int = 3,
    base_delay: float = 2.0,
) -> tuple[int, str]:
    """run_capture with exponential-backoff retry on non-zero exit (transient GCS errors)."""
    rc, text = 1, ""
    for attempt in range(1, attempts + 1):
        rc, text = run_capture(cmd)
        if rc == 0 or attempt >= attempts:
            return rc, text
        time.sleep(base_delay * (2 ** (attempt - 1)))
    return rc, text


def download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a GCS object as JSON; return (payload, None) or (None, error_message)."""
    with tempfile.TemporaryDirectory(prefix="ci_verdict_") as tmp_dir:
        local_path = Path(tmp_dir) / "payload.json"
        rc, err = run_capture_retry(["gcloud", "storage", "cp", uri, str(local_path), "--quiet"])
        if rc != 0:
            return None, err

        try:
            payload = json.loads(local_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return None, f"invalid_json: {exc}"
        if not isinstance(payload, dict):
            return None, "invalid_json: expected object"
        return payload, None


def upload_json(uri: str, payload: dict[str, Any]) -> None:
    """Upload a JSON object to GCS."""
    with tempfile.TemporaryDirectory(prefix="ci_trigger_") as tmp_dir:
        local_path = Path(tmp_dir) / "payload.json"
        local_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        rc, err = run_capture_retry(["gcloud", "storage", "cp", str(local_path), uri, "--quiet"])
        if rc != 0:
            raise GcloudError(f"Failed to upload {uri}: {err}")


def gcs_exists(uri: str) -> bool:
    """Return True when an object exists."""
    rc, _ = run_capture(["gcloud", "storage", "ls", uri])
    return rc == 0


def vm_start(project: str, zone: str, instance_name: str) -> None:
    """Start a stopped Compute Engine instance. Raises GcloudError on failure."""
    cmd = [
        "gcloud",
        "compute",
        "instances",
        "start",
        instance_name,
        "--zone",
        zone,
        "--project",
        project,
    ]
    rc, err = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to start VM {instance_name}: {err}")


def vm_describe(project: str, zone: str, instance_name: str) -> dict[str, Any]:
    """Describe a Compute Engine instance as JSON."""
    cmd = [
        "gcloud",
        "compute",
        "instances",
        "describe",
        instance_name,
        "--zone",
        zone,
        "--project",
        project,
        "--format=json",
    ]
    rc, out = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to describe VM {instance_name}: {out}")
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise GcloudError(f"Invalid JSON while describing VM {instance_name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GcloudError(f"Invalid VM describe payload for {instance_name}: expected object")
    return payload


def vm_serial_output(project: str, zone: str, instance_name: str) -> str:
    """Fetch serial output text for a VM."""
    cmd = [
        "gcloud",
        "compute",
        "instances",
        "get-serial-port-output",
        instance_name,
        "--zone",
        zone,
        "--project",
        project,
    ]
    rc, out = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to get serial output for {instance_name}: {out}")
    return out


def vm_serial_output_retry(
    project: str,
    zone: str,
    instance_name: str,
    *,
    attempts: int = 4,
    base_delay_sec: float = 2.0,
) -> str:
    """Fetch serial output with retry for startup races."""
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            return vm_serial_output(project, zone, instance_name)
        except GcloudError as exc:
            last_error = str(exc)
            if attempt >= attempts:
                break
            time.sleep(base_delay_sec * (2 ** (attempt - 1)))
    raise GcloudError(last_error or f"Failed to get serial output for {instance_name}")


def vm_add_metadata(
    project: str,
    zone: str,
    instance_name: str,
    metadata: dict[str, str],
    *,
    metadata_files: dict[str, Path] | None = None,
) -> None:
    """Set custom metadata keys and optional metadata-from-file values on a Compute Engine instance."""
    cmd = [
        "gcloud",
        "compute",
        "instances",
        "add-metadata",
        instance_name,
        "--zone",
        zone,
        "--project",
        project,
    ]
    if metadata:
        metadata_items = ",".join(f"{k}={v}" for k, v in metadata.items())
        cmd.extend(["--metadata", metadata_items])
    if metadata_files:
        metadata_file_items = ",".join(f"{k}={v}" for k, v in metadata_files.items())
        cmd.extend(["--metadata-from-file", metadata_file_items])
    if not metadata and not metadata_files:
        raise GcloudError(f"No metadata provided for {instance_name}")
    rc, err = run_capture(cmd)
    if rc != 0:
        raise GcloudError(f"Failed to update VM metadata for {instance_name}: {err}")

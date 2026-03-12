"""BMT shared runtime: constants, GCS/VM operations, config loading, and output helpers."""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from cli.shared.config import (
    BmtConfig as BmtConfig,
)
from cli.shared.config import (
    get_config as get_config,
)
from cli.shared.config import (
    load_bmt_config as load_bmt_config,
)

# ── Path defaults ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG_ROOT = "gcp/code"
DEFAULT_ENV_CONTRACT_PATH = "tools/repo_vars_contract.py"

# ── Errors ─────────────────────────────────────────────────────────────────────


class ConfigError(RuntimeError):
    """Raised when CI config files are missing or invalid."""


class GcloudError(RuntimeError):
    """Raised when a gcloud command fails in a non-recoverable way."""


# ── URI helpers ────────────────────────────────────────────────────────────────

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def bucket_uri(bucket_root: str, rel_path: str) -> str:
    return f"{bucket_root}/{rel_path.lstrip('/')}"


def code_bucket_root_uri(bucket: str) -> str:
    return f"gs://{bucket}/code"


def runtime_bucket_root_uri(bucket: str) -> str:
    return f"gs://{bucket}/runtime"


def sanitize_run_id(raw: str) -> str:
    value = _RUN_ID_SAFE.sub("-", raw.strip())
    value = value.strip("-._")
    if not value:
        raise ValueError("run_id is empty after sanitization")
    return value[:200]


def run_trigger_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/runs/{safe_run_id}.json")


def run_handshake_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/acks/{safe_run_id}.json")


def run_status_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/status/{safe_run_id}.json")


# ── Decision exit codes (for gate/verdict CLI output) ──────────────────────────

DECISION_ACCEPTED = "accepted"
DECISION_ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
DECISION_REJECTED = "rejected"
DECISION_TIMEOUT = "timeout"


def decision_exit(decision: str) -> int:
    """Return exit code for a gate decision: 0 for accepted, non-zero for rejected/timeout."""
    if decision in (DECISION_ACCEPTED, DECISION_ACCEPTED_WITH_WARNINGS):
        return 0
    return 1


# ── Env helpers ────────────────────────────────────────────────────────────────


def require_env(name: str) -> str:
    """Return env var value or raise RuntimeError if unset/empty."""
    val = os.environ.get(name, "")
    if not val.strip():
        raise RuntimeError(f"Required env var {name!r} is not set or empty")
    return val.strip()


def _workflow_run_id() -> str:
    """Return WORKFLOW_RUN_ID or GITHUB_RUN_ID; raise if unset."""
    run_id = os.environ.get("WORKFLOW_RUN_ID") or os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        raise RuntimeError("WORKFLOW_RUN_ID or GITHUB_RUN_ID is required")
    return str(run_id)


def _workflow_runtime_root() -> str:
    """Return gs://{GCS_BUCKET}/runtime; raise if GCS_BUCKET unset."""
    bucket = os.environ.get("GCS_BUCKET")
    if not bucket:
        raise RuntimeError("GCS_BUCKET is required")
    return f"gs://{bucket}/runtime"


# ── GCS / VM operations ────────────────────────────────────────────────────────

# GCS: delegate to cli.gcs (google-cloud-storage). VM: still gcloud subprocess.


def _gcs_download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    from cli import gcs

    return gcs.download_json(uri)


def _gcs_upload_json(uri: str, payload: dict[str, Any]) -> None:
    from cli import gcs

    try:
        gcs.upload_json(uri, payload)
    except gcs.GcsError as exc:
        raise GcloudError(str(exc)) from exc


def _gcs_exists(uri: str) -> bool:
    from cli import gcs

    return gcs.object_exists(uri)


def download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a GCS object as JSON; return (payload, None) or (None, error_message)."""
    return _gcs_download_json(uri)


def upload_json(uri: str, payload: dict[str, Any]) -> None:
    """Upload a JSON object to GCS."""
    _gcs_upload_json(uri, payload)


def gcs_exists(uri: str) -> bool:
    """Return True when an object exists in GCS."""
    return _gcs_exists(uri)


def run_capture(cmd: list[str]) -> tuple[int, str]:
    """Run command; return (exit_code, stderr or stdout)."""
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    text = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode, text


def run_capture_retry(
    cmd: list[str], attempts: int = 3, base_delay: float = 2.0
) -> tuple[int, str]:
    """run_capture with exponential-backoff retry on non-zero exit (transient GCS errors)."""
    rc, text = 1, ""
    for attempt in range(1, attempts + 1):
        rc, text = run_capture(cmd)
        if rc == 0 or attempt >= attempts:
            return rc, text
        time.sleep(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5))  # noqa: S311
    return rc, text


def _compute_client() -> "google.cloud.compute_v1.InstancesClient":
    """Lazy-init Compute Engine client."""
    from google.cloud import compute_v1  # noqa: I001

    return compute_v1.InstancesClient()


def vm_start(project: str, zone: str, instance_name: str) -> None:
    """Start a stopped Compute Engine instance."""
    try:
        op = _compute_client().start(project=project, zone=zone, instance=instance_name)
        op.result()  # wait for completion
    except Exception as exc:
        raise GcloudError(f"Failed to start VM {instance_name}: {exc}") from exc


def vm_stop(project: str, zone: str, instance_name: str) -> None:
    """Stop a running Compute Engine instance."""
    try:
        op = _compute_client().stop(project=project, zone=zone, instance=instance_name)
        op.result()  # wait for completion
    except Exception as exc:
        raise GcloudError(f"Failed to stop VM {instance_name}: {exc}") from exc


def vm_describe(project: str, zone: str, instance_name: str) -> dict[str, Any]:
    """Describe a Compute Engine instance as a dict."""
    try:
        from google.cloud.compute_v1.types import Instance  # noqa: I001
        from google.protobuf.json_format import MessageToDict

        instance: Instance = _compute_client().get(
            project=project, zone=zone, instance=instance_name,
        )
        return MessageToDict(instance._pb, preserving_proto_field_name=True)
    except Exception as exc:
        raise GcloudError(f"Failed to describe VM {instance_name}: {exc}") from exc


def vm_list_names(
    project: str, zone: str, *, filter_expr: str | None = None
) -> list[str]:
    """List instance names in a zone; optional filter (e.g. labels.bmt-gate=true). Uses google-cloud-compute SDK."""
    try:
        client = _compute_client()
        if filter_expr:
            it = client.list(project=project, zone=zone, filter=filter_expr)
        else:
            it = client.list(project=project, zone=zone)
        return [inst.name for inst in it if getattr(inst, "name", None)]
    except Exception as exc:
        raise GcloudError(f"Failed to list instances in {project}/{zone}: {exc}") from exc


def vm_serial_output(project: str, zone: str, instance_name: str) -> str:
    """Fetch serial output text for a VM."""
    try:
        resp = _compute_client().get_serial_port_output(
            project=project, zone=zone, instance=instance_name,
        )
        return resp.contents or ""
    except Exception as exc:
        raise GcloudError(f"Failed to get serial output for {instance_name}: {exc}") from exc


def vm_serial_output_retry(
    project: str, zone: str, instance_name: str, *, attempts: int = 4, base_delay_sec: float = 2.0
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
    if not metadata and not metadata_files:
        raise GcloudError(f"No metadata provided for {instance_name}")
    try:
        from google.cloud.compute_v1.types import Metadata, Items  # noqa: I001

        # Get current metadata (need fingerprint for CAS update)
        instance = _compute_client().get(
            project=project, zone=zone, instance=instance_name,
        )
        existing = {}
        fingerprint = ""
        if instance.metadata:
            fingerprint = instance.metadata.fingerprint or ""
            for item in instance.metadata.items_:
                existing[item.key] = item.value

        # Merge new metadata
        existing.update(metadata)
        if metadata_files:
            for key, path in metadata_files.items():
                existing[key] = Path(path).read_text(encoding="utf-8")

        items = [Items(key=k, value=v) for k, v in existing.items()]
        meta = Metadata(items=items, fingerprint=fingerprint)

        op = _compute_client().set_metadata(
            project=project, zone=zone, instance=instance_name, metadata_resource=meta,
        )
        op.result()
    except GcloudError:
        raise
    except Exception as exc:
        raise GcloudError(f"Failed to update VM metadata for {instance_name}: {exc}") from exc


# ── Config loading ─────────────────────────────────────────────────────────────


def read_json_object(path: Path) -> dict[str, Any]:
    """Load and validate a JSON file as a single object; raises ConfigError if missing/invalid."""
    if not path.is_file():
        raise ConfigError(f"Missing JSON file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Expected JSON object at {path}")
    return data


# ── GitHub output helpers ──────────────────────────────────────────────────────


def write_github_output(github_output: str | None, key: str, value: str) -> None:
    """Append key=value to GITHUB_OUTPUT file (silently no-ops if path is None)."""
    if not github_output:
        return
    with Path(github_output).open("a", encoding="utf-8") as fh:
        _ = fh.write(f"{key}={value}\n")

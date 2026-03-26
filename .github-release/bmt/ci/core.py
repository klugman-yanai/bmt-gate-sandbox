"""Errors, URI helpers, env helpers, JSON loading. No GCS/VM (use ci.gcs and ci.vm)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ConfigError(RuntimeError):
    """Raised when CI config files are missing or invalid."""


class GcloudError(RuntimeError):
    """Raised when a GCP operation fails in a non-recoverable way."""


DEFAULT_CONFIG_ROOT = "backend"
DEFAULT_ENV_CONTRACT_PATH = "tools/repo/vars_contract.py"

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def bucket_uri(bucket_root: str, rel_path: str) -> str:
    return f"{bucket_root}/{rel_path.lstrip('/')}"


def bucket_root_uri(bucket: str) -> str:
    """Bucket root: gs://<bucket>. No code/ or runtime/ prefix."""
    return f"gs://{bucket}"


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


DECISION_ACCEPTED = "accepted"
DECISION_ACCEPTED_WITH_WARNINGS = "accepted_with_warnings"
DECISION_REJECTED = "rejected"
DECISION_TIMEOUT = "timeout"


def decision_exit(decision: str) -> int:
    """Return exit code for a gate decision: 0 for accepted, non-zero for rejected/timeout."""
    if decision in (DECISION_ACCEPTED, DECISION_ACCEPTED_WITH_WARNINGS):
        return 0
    return 1


def require_env(name: str) -> str:
    """Return env var value or raise RuntimeError if unset/empty."""
    import os

    val = os.environ.get(name, "")
    if not val.strip():
        raise RuntimeError(f"Required env var {name!r} is not set or empty")
    return val.strip()


def workflow_run_id() -> str:
    """Return WORKFLOW_RUN_ID or GITHUB_RUN_ID; raise if unset."""
    import os

    run_id = os.environ.get("WORKFLOW_RUN_ID") or os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        raise RuntimeError("WORKFLOW_RUN_ID or GITHUB_RUN_ID is required")
    return str(run_id)


def workflow_runtime_root() -> str:
    """Return gs://{GCS_BUCKET} (bucket root); raise if GCS_BUCKET unset."""
    import os

    bucket = os.environ.get("GCS_BUCKET")
    if not bucket:
        raise RuntimeError("GCS_BUCKET is required")
    return f"gs://{bucket}"


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

"""Errors, URI helpers, env helpers, JSON loading. No GCS/VM (use ci.gcs and ci.vm)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import gcp.image.config.constants as _bmt_constants
from gcp.image.config.decisions import GateDecision
from gcp.image.config.value_types import sanitize_run_id

# Re-export gate decision strings for `from ci.core import DECISION_*` (tests, callers).
DECISION_ACCEPTED = _bmt_constants.DECISION_ACCEPTED
DECISION_ACCEPTED_WITH_WARNINGS = _bmt_constants.DECISION_ACCEPTED_WITH_WARNINGS
DECISION_REJECTED = _bmt_constants.DECISION_REJECTED
DECISION_TIMEOUT = _bmt_constants.DECISION_TIMEOUT


class ConfigError(RuntimeError):
    """Raised when CI config files are missing or invalid."""


class GcloudError(RuntimeError):
    """Raised when a GCP operation fails in a non-recoverable way."""


DEFAULT_CONFIG_ROOT = "gcp/image"
DEFAULT_ENV_CONTRACT_PATH = "tools/repo/vars_contract.py"

# Trigger path subdirectories under {bucket_root}/triggers/
TRIGGER_RUNS_SUBDIR = "runs"
TRIGGER_ACKS_SUBDIR = "acks"
TRIGGER_STATUS_SUBDIR = "status"
TRIGGER_REPORTING_SUBDIR = "reporting"


def bucket_uri(bucket_root: str, rel_path: str) -> str:
    return f"{bucket_root}/{rel_path.lstrip('/')}"


def bucket_root_uri(bucket: str) -> str:
    """Bucket root: gs://<bucket>. No code/ or runtime/ prefix."""
    return f"gs://{bucket}"


def run_trigger_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/{TRIGGER_RUNS_SUBDIR}/{safe_run_id}.json")


def run_handshake_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/{TRIGGER_ACKS_SUBDIR}/{safe_run_id}.json")


def run_status_uri(runtime_bucket_root: str, workflow_run_id: str) -> str:
    safe_run_id = sanitize_run_id(workflow_run_id)
    return bucket_uri(runtime_bucket_root, f"triggers/{TRIGGER_STATUS_SUBDIR}/{safe_run_id}.json")


def decision_exit(decision: str | GateDecision) -> int:
    """Return exit code for a gate decision: 0 for accepted, non-zero for rejected/timeout."""
    if isinstance(decision, GateDecision):
        d = decision
    else:
        try:
            d = GateDecision(decision)
        except ValueError:
            return 1
    return 0 if d in (GateDecision.ACCEPTED, GateDecision.ACCEPTED_WITH_WARNINGS) else 1


def require_env(name: str) -> str:
    """Return env var value or raise RuntimeError if unset/empty."""
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"Required env var {name!r} is not set or empty")
    return value


def workflow_run_id() -> str:
    """Return WORKFLOW_RUN_ID or GITHUB_RUN_ID; raise if unset."""
    run_id = (os.environ.get("WORKFLOW_RUN_ID") or os.environ.get("GITHUB_RUN_ID") or "").strip()
    if not run_id:
        raise RuntimeError("WORKFLOW_RUN_ID or GITHUB_RUN_ID is required")
    return run_id


def workflow_runtime_root() -> str:
    """Return gs://{GCS_BUCKET} (bucket root); raise if GCS_BUCKET unset."""
    from gcp.image.config.constants import ENV_GCS_BUCKET

    return f"gs://{require_env(ENV_GCS_BUCKET)}"


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

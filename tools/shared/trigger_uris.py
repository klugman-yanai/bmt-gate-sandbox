"""Trigger and handshake URIs for BMT run triggers (tools-only; no dependency on .github/bmt).

Same path and sanitization contract as .github/bmt/ci/core so trigger/ack paths
match between CI, VM, and tools.
"""

from __future__ import annotations

from backend.config.value_types import sanitize_run_id

__all__ = ["run_handshake_uri", "run_trigger_uri", "runtime_root_uri", "sanitize_run_id"]


def runtime_root_uri(bucket: str) -> str:
    """Runtime root for triggers/acks. Matches VM and CI: gs://<bucket> (no /runtime prefix)."""
    return f"gs://{bucket}"


def run_trigger_uri(runtime_root: str, workflow_run_id: str) -> str:
    """GCS URI for run trigger JSON: triggers/runs/<safe_id>.json."""
    safe = sanitize_run_id(workflow_run_id)
    return f"{runtime_root.rstrip('/')}/triggers/runs/{safe}.json"


def run_handshake_uri(runtime_root: str, workflow_run_id: str) -> str:
    """GCS URI for handshake ack JSON: triggers/acks/<safe_id>.json."""
    safe = sanitize_run_id(workflow_run_id)
    return f"{runtime_root.rstrip('/')}/triggers/acks/{safe}.json"

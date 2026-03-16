"""Trigger and handshake URIs for BMT run triggers (tools-only; no dependency on .github/bmt).

Same path and sanitization contract as .github/bmt/ci/core so trigger/ack paths
match between CI, VM, and tools.
"""

from __future__ import annotations

import re

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
_MAX_RUN_ID_LEN = 200


def sanitize_run_id(raw: str) -> str:
    """Normalize workflow_run_id for use in GCS object paths. Matches .github/bmt/ci/core."""
    value = _RUN_ID_SAFE.sub("-", (raw or "").strip())
    value = value.strip("-._")
    if not value:
        raise ValueError("run_id is empty after sanitization")
    return value[:_MAX_RUN_ID_LEN]


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

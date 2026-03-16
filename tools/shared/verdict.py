"""Shared GCS/verdict helpers for polling and aggregating BMT verdicts.

Used by tools/wait_verdicts. Uses gcloud CLI only (no google-cloud-storage)
so tools/ does not depend on .github/bmt CLI.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

_RUN_ID_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_run_id(raw: str) -> str:
    value = _RUN_ID_SAFE.sub("-", raw.strip()).strip("-._")
    if not value:
        raise ValueError("run_id is empty after sanitization")
    return value[:200]


def snapshot_verdict_uri(bucket_root: str, results_prefix: str, run_id: str) -> str:
    """GCS URI for ci_verdict.json of a given run."""
    cleaned = results_prefix.rstrip("/")
    safe = sanitize_run_id(run_id)
    return f"{bucket_root}/{cleaned}/snapshots/{safe}/ci_verdict.json"


def current_pointer_uri(bucket_root: str, results_prefix: str) -> str:
    """GCS URI for current.json pointer at results prefix."""
    return f"{bucket_root}/{results_prefix.rstrip('/')}/current.json"


def download_json(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Download a GCS object as JSON via gcloud storage cat. Return (payload, None) or (None, error_message)."""
    proc = subprocess.run(
        ["gcloud", "storage", "cat", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return None, err or "gcloud storage cat failed"
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return None, f"invalid_json: {e}"
    if not isinstance(payload, dict):
        return None, "invalid_json: expected object"
    return payload, None

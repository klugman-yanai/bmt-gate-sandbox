"""Shared GCS/verdict helpers for polling and aggregating BMT verdicts.

Used by tools/wait_verdicts. Uses gcloud CLI only (no google-cloud-storage)
so tools/ does not depend on the kardome-bmt CLI.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from runtime.config.value_types import (
    ResultsPath,
    RunId,
    as_results_path,
    results_path_str,
    sanitize_run_id,
)

__all__ = [
    "ResultsPath",
    "RunId",
    "as_results_path",
    "current_pointer_uri",
    "download_json",
    "results_path_str",
    "sanitize_run_id",
    "snapshot_verdict_uri",
]


def snapshot_verdict_uri(bucket_root: str, results_path: ResultsPath | str, run_id: RunId | str) -> str:
    """GCS URI for ci_verdict.json of a given run."""
    rp = results_path_str(as_results_path(str(results_path)))
    safe = sanitize_run_id(str(run_id))
    return f"{bucket_root}/{rp}/snapshots/{safe}/ci_verdict.json"


def current_pointer_uri(bucket_root: str, results_path: ResultsPath | str) -> str:
    """GCS URI for current.json pointer under the results path."""
    rp = results_path_str(as_results_path(str(results_path)))
    return f"{bucket_root}/{rp}/current.json"


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

"""Fetch BMT run trigger and handshake ack from GCS. Phase 1: GCS only (no VM serial)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

from tools.shared.trigger_uris import (
    run_handshake_uri,
    run_trigger_uri,
    runtime_root_uri,
    sanitize_run_id,
)
from tools.shared.verdict import download_json as gcs_download_json


@dataclass(slots=True)
class VmCheckResult:
    """Structured result of vm-check: trigger and ack payloads from GCS."""

    run_id: str
    trigger_uri: str
    ack_uri: str
    trigger_payload: dict[str, Any] | None
    ack_payload: dict[str, Any] | None
    trigger_error: str | None
    ack_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def run(run_id: str, bucket: str | None = None) -> int:
    """Fetch trigger and ack JSON from GCS; print and return 0 if ack found, else 1.

    Uses GCS_BUCKET if bucket is None. Run_id is sanitized for GCS paths.
    """
    if not (bucket or "").strip():
        bucket = (os.environ.get("GCS_BUCKET") or "").strip()
    if not bucket:
        print("error: GCS_BUCKET not set and no --bucket provided", flush=True)
        return 1
    try:
        safe_id = sanitize_run_id(run_id)
    except ValueError as e:
        print(f"error: invalid run_id: {e}", flush=True)
        return 1

    root = runtime_root_uri(bucket)
    trigger_uri = run_trigger_uri(root, safe_id)
    ack_uri = run_handshake_uri(root, safe_id)

    trigger_payload, trigger_error = gcs_download_json(trigger_uri)
    ack_payload, ack_error = gcs_download_json(ack_uri)

    result = VmCheckResult(
        run_id=safe_id,
        trigger_uri=trigger_uri,
        ack_uri=ack_uri,
        trigger_payload=trigger_payload,
        ack_payload=ack_payload,
        trigger_error=trigger_error,
        ack_error=ack_error,
    )
    print(result.to_json(), flush=True)

    if ack_payload is not None:
        return 0
    return 1

"""Trigger processing pipeline facade (L4 — imports from L0-L3, NOT from vm_watcher).

Combines trigger download, leg resolution, handshake ack building, and leg list
construction into a reusable pipeline. The watcher calls this; coordinator and
Cloud Run jobs can also use it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gcp.image.config.constants import DECISION_ACCEPTED, DECISION_REJECTED
from gcp.image.gcs_helpers import _gcloud_download_json, _gcloud_rm, _gcloud_upload_json
from gcp.image.models import LegIdentity, TriggerPayload
from gcp.image.trigger_resolution import (
    _resolve_requested_legs,
    _run_handshake_uri_from_trigger_uri,
)
from gcp.image.utils import _bucket_uri, _now_iso, _runtime_bucket_root


# ---------------------------------------------------------------------------
# Trigger download
# ---------------------------------------------------------------------------


def download_trigger(uri: str) -> TriggerPayload | None:
    """Download and parse a trigger JSON from GCS. Returns None on failure (deletes invalid JSON)."""
    downloaded = _gcloud_download_json(uri)
    if isinstance(downloaded, tuple) and len(downloaded) == 2:
        payload, error = downloaded
    else:
        payload = downloaded if isinstance(downloaded, dict) else None
        error = None

    if payload is None:
        if error == "invalid_json":
            _gcloud_rm(uri)
        return None

    return payload  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Leg resolution and list building
# ---------------------------------------------------------------------------


def resolve_legs(
    trigger: TriggerPayload,
    repo_root: Path,
    *,
    exists_func: Callable[[Path], bool] | None = None,
    load_jobs_func: Callable[[Path, str], tuple[dict[str, Any] | None, str | None]] | None = None,
) -> list[dict[str, Any]]:
    """Resolve trigger legs against the local runtime (baked image). Returns typed leg dicts."""
    legs_raw = trigger.get("legs") or []
    if not isinstance(legs_raw, list):
        legs_raw = []
    return _resolve_requested_legs(
        legs_raw=legs_raw,
        repo_root=repo_root,
        _exists_func=exists_func,
        _load_jobs_func=load_jobs_func,
    )


def split_legs(
    requested_legs: list[dict[str, Any]],
    *,
    skip_all: bool = False,
    skip_reason: str | None = None,
) -> tuple[list[LegIdentity], list[dict[str, Any]]]:
    """Split resolved legs into accepted (as LegIdentity) and rejected lists.

    If ``skip_all`` is True, all legs are rejected with the given reason.
    Returns (accepted_legs, rejected_legs).
    """
    if skip_all:
        for leg in requested_legs:
            leg["decision"] = DECISION_REJECTED
            leg["reason"] = skip_reason or "skipped"

    accepted: list[LegIdentity] = []
    rejected: list[dict[str, Any]] = []

    for leg in requested_legs:
        decision = leg.get("decision", DECISION_REJECTED)
        if decision == DECISION_ACCEPTED:
            accepted.append(
                LegIdentity(
                    project=str(leg.get("project", "?")),
                    bmt_id=str(leg.get("bmt_id", "?")),
                    run_id=str(leg.get("run_id", "?")),
                    index=int(leg.get("index", 0)),
                )
            )
        else:
            rejected.append({
                "index": int(leg.get("index", -1)),
                "project": str(leg.get("project", "?")),
                "bmt_id": str(leg.get("bmt_id", "?")),
                "run_id": str(leg.get("run_id", "?")),
                "reason": str(leg.get("reason") or "invalid_leg_type"),
            })

    return accepted, rejected


# ---------------------------------------------------------------------------
# Handshake
# ---------------------------------------------------------------------------


def build_handshake_payload(
    *,
    trigger_uri: str,
    trigger: TriggerPayload,
    requested_legs: list[dict[str, Any]],
    accepted_legs: list[LegIdentity],
    rejected_legs: list[dict[str, Any]],
    skip_reason: str | None,
    superseded_by_sha: str | None,
) -> dict[str, Any]:
    """Build the handshake ack payload without writing it."""
    accepted_count = len(accepted_legs)
    if skip_reason:
        disposition = "skipped"
    elif accepted_count == 0:
        disposition = "accepted_but_empty"
    else:
        disposition = "accepted"

    return {
        "support_resolution_version": "v2",
        "workflow_run_id": str(trigger.get("workflow_run_id", "?")),
        "received_at": _now_iso(),
        "repository": str(trigger.get("repository", "")),
        "sha": str(trigger.get("sha", "")),
        "run_context": str(trigger.get("run_context", "manual")),
        "run_trigger_uri": trigger_uri,
        "requested_leg_count": len(requested_legs),
        "accepted_leg_count": accepted_count,
        "requested_legs": requested_legs,
        "accepted_legs": [
            {"project": leg.project, "bmt_id": leg.bmt_id, "run_id": leg.run_id} for leg in accepted_legs
        ],
        "rejected_legs": rejected_legs,
        "run_disposition": disposition,
        "skip_reason": skip_reason,
        "superseded_by_sha": superseded_by_sha,
    }


def write_handshake(trigger_uri: str, payload: dict[str, Any]) -> bool:
    """Write the handshake ack to GCS."""
    ack_uri = _run_handshake_uri_from_trigger_uri(trigger_uri)
    return _gcloud_upload_json(ack_uri, payload)


# ---------------------------------------------------------------------------
# Verdict aggregation (thin wrapper — delegates to existing module)
# ---------------------------------------------------------------------------


def aggregate_verdicts(summaries: list[dict[str, Any] | None]) -> tuple[str, str]:
    """Aggregate manager summaries into (state, description). state: success|failure."""
    from gcp.image.verdict_aggregation import _aggregate_verdicts_from_summaries

    return _aggregate_verdicts_from_summaries(summaries)
